"""User routes — list, create, update, delete, batch."""

import hashlib
import re
import secrets
import string
import time
import uuid
from datetime import datetime
import bcrypt as _bcrypt
from flask import Blueprint, request, jsonify, session
from sqlalchemy import func, text
from app.extensions import db
from app.models import PteroServer, PteroUser
from app.config import config_manager
from app.utils import log_activity
from app.services import pterodactyl as ptero
from app.services import email as email_svc

bp = Blueprint('users', __name__)


def _processed_users(args):
    """Fetch, filter, sort users from DB + server counts."""
    search = args.get('search_term', '').strip().lower()
    filter_status = args.get('filter_server_status', 'all')
    sort_by = args.get('sort_by', 'id')
    sort_order = args.get('sort_order', 'desc')

    query = PteroUser.query
    if search:
        query = query.filter(
            db.or_(
                PteroUser.username.ilike(f'%{search}%'),
                PteroUser.email.ilike(f'%{search}%'),
            )
        )

    all_users_db = query.all()

    server_counts = dict(
        db.session.query(PteroServer.owner_id, func.count(PteroServer.owner_id))
        .group_by(PteroServer.owner_id).all()
    )

    all_users = []
    for u in all_users_db:
        sc = server_counts.get(u.id, 0)
        all_users.append({
            'id': u.id,
            'uuid': u.uuid,
            'username': u.username,
            'email': u.email,
            'first_name': u.name_first,
            'last_name': u.name_last,
            'root_admin': u.root_admin,
            '2fa_enabled': False,
            'language': u.language,
            'created_at': u.created_at.isoformat() if u.created_at else None,
            'updated_at': u.updated_at.isoformat() if u.updated_at else None,
            'server_count': sc,
        })

    if filter_status == 'has_servers':
        all_users = [u for u in all_users if u['server_count'] > 0]
    elif filter_status == 'no_servers':
        all_users = [u for u in all_users if u['server_count'] == 0]

    key_map = {
        'username': lambda u: u.get('username', '').lower(),
        'id': lambda u: u.get('id', 0),
        'server_count': lambda u: u.get('server_count', 0),
    }
    all_users.sort(key=key_map.get(sort_by, key_map['username']), reverse=(sort_order == 'desc'))
    return all_users


@bp.route('/users')
def list_users():
    users = _processed_users(request.args)
    return jsonify({'users': users})


def _generate_password(length: int = 16) -> str:
    """Generate a random password with letters, digits and punctuation."""
    alphabet = string.ascii_letters + string.digits + '!@#$%&*'
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _create_password_reset_token(email: str) -> str:
    """Create a password reset token compatible with Laravel's PasswordBroker.

    Generates a random token, stores its bcrypt hash in password_resets table,
    and returns the raw token for use in the reset URL.
    """
    # Generate a 64-char hex token (same as Laravel: hash_hmac('sha256', random(40), key))
    raw_token = secrets.token_hex(32)

    # Hash the token with bcrypt (Laravel stores bcrypt of the token)
    hashed = _bcrypt.hashpw(raw_token.encode(), _bcrypt.gensalt(rounds=10)).decode()
    # Convert to $2y$ prefix for PHP/Laravel compatibility
    if hashed.startswith('$2b$'):
        hashed = '$2y$' + hashed[4:]

    # Delete any existing token for this email, then insert new one
    now = datetime.utcnow()
    db.session.execute(text("DELETE FROM password_resets WHERE email = :email"), {'email': email})
    db.session.execute(
        text("INSERT INTO password_resets (email, token, created_at) VALUES (:email, :token, :created_at)"),
        {'email': email, 'token': hashed, 'created_at': now},
    )
    db.session.commit()

    return raw_token


@bp.route('/users', methods=['POST'])
def create_user():
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip()
    username = data.get('username', '').strip()
    if not email or not username:
        return jsonify({'error': '邮箱和用户名不能为空'}), 400

    # Pterodactyl username rules: lowercase alphanumeric + hyphens, must start/end with alnum
    if not re.match(r'^[a-z0-9]([-a-z0-9]*[a-z0-9])?$', username):
        return jsonify({'error': '用户名只能包含小写字母、数字和连字符，且必须以字母或数字开头和结尾'}), 422

    first_name = data.get('firstName', '').strip() or username
    last_name = data.get('lastName', '').strip() or 'User'
    send_welcome = data.get('sendWelcome', True)

    # Check duplicates
    if PteroUser.query.filter_by(email=email).first():
        return jsonify({'error': f'邮箱 {email} 已存在'}), 422
    if PteroUser.query.filter_by(username=username).first():
        return jsonify({'error': f'用户名 {username} 已存在'}), 422

    actor = session.get('admin_username', '未知管理员')

    try:
        now = datetime.utcnow()
        user = PteroUser(
            uuid=str(uuid.uuid4()),
            username=username,
            email=email,
            name_first=first_name,
            name_last=last_name,
            root_admin=False,
            language='en',
            use_totp=False,
            gravatar=True,
            created_at=now,
            updated_at=now,
        )
        # Generate a random password (user will set their own via reset link)
        user.set_password(_generate_password(30))
        db.session.add(user)
        db.session.commit()

        # Create password reset token and send welcome email
        email_sent = False
        if send_welcome:
            token = _create_password_reset_token(email)
            panel_url = config_manager.get('PTERO_PANEL_URL', '').rstrip('/')
            reset_url = f'{panel_url}/auth/password/reset/{token}?email={email}'

            tpl = email_svc.load_template('create_user')
            panel_name = config_manager.get('BRAND_NAME', 'Ptero Manager')
            ctx = {
                '{{username}}': username,
                '{{panel_name}}': panel_name,
                '{{panel_url}}': panel_url,
            }
            subject, body = email_svc.render_template_body(tpl, ctx)
            ok, msg = email_svc.send_email(
                email, subject, body,
                greeting=f'你好, {first_name}!',
                action_text='设置您的账户密码',
                action_url=reset_url,
            )
            email_sent = ok

        log_activity(actor, 'create_user', '成功', f"创建用户 '{username}' (Email: {email})。")
        result = {'message': f"用户 '{username}' 创建成功", 'user': {'id': user.id, 'username': username}}
        if send_welcome:
            result['emailSent'] = email_sent
        return jsonify(result), 201
    except Exception as e:
        db.session.rollback()
        log_activity(actor, 'create_user', '失败', f"创建用户 '{username}' 失败: {e}")
        return jsonify({'error': f'创建用户失败: {e}'}), 500


@bp.route('/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    data = request.get_json(silent=True) or {}
    actor = session.get('admin_username', '未知管理员')

    # Fetch current data
    current = ptero.get_single(f"users/{user_id}")
    if not current:
        return jsonify({'error': '无法获取用户数据'}), 500

    payload = {
        'username': data.get('username', current.get('username', '')),
        'email': data.get('email', current.get('email', '')),
        'first_name': data.get('firstName', current.get('first_name', '')),
        'last_name': data.get('lastName', current.get('last_name', '')),
    }
    if data.get('password'):
        payload['password'] = data['password']

    result, err = ptero.update_user(user_id, payload)
    if result:
        log_activity(actor, 'edit_user', '成功', f"更新用户 ID {user_id}。")
        return jsonify({'message': '用户已更新'})

    log_activity(actor, 'edit_user', '失败', f"更新用户 ID {user_id} 失败。")
    return jsonify({'error': err or '更新失败'}), 422 if err else 500


@bp.route('/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    actor = session.get('admin_username', '未知管理员')

    # Delete owned servers first via API (DB cascade handles manager_server_meta)
    owned = PteroServer.query.filter_by(owner_id=user_id).all()
    for srv in owned:
        ptero.delete_server_from_panel(srv.id)
    db.session.expire_all()

    if ptero.delete_user_from_panel(user_id):
        log_activity(actor, 'delete_user', '成功', f"删除用户 ID {user_id} 及其 {len(owned)} 台服务器。")
        return jsonify({'message': f'用户及其 {len(owned)} 台服务器已删除'})

    log_activity(actor, 'delete_user', '失败', f"删除用户 ID {user_id} 失败。")
    return jsonify({'error': '删除用户失败'}), 500


@bp.route('/users/batch', methods=['POST'])
def batch_users():
    """Batch operations on users (email, delete)."""
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    user_ids = data.get('userIds', [])
    if not action or not user_ids:
        return jsonify({'error': '未选择操作或用户'}), 400

    actor = session.get('admin_username', '未知管理员')
    success, errors = 0, 0

    if action == 'email':
        tpl = email_svc.load_template('bulk')
        users_data = ptero.get_data('users')
        if not users_data:
            return jsonify({'error': '无法获取用户列表'}), 502

        selected_ids = set(user_ids)
        targets = [u['attributes'] for u in users_data if u['attributes']['id'] in selected_ids]
        panel_name = config_manager.get('BRAND_NAME', 'Ptero Manager')
        panel_url = config_manager.get('PTERO_PANEL_URL', '')

        for user in targets:
            if not user.get('email'):
                errors += 1
                continue
            ctx = {
                '{{panel_name}}': panel_name,
                '{{username}}': user.get('username', '未知用户'),
                '{{email}}': user.get('email', ''),
                '{{server_name}}': '(不适用)',
                '{{server_id}}': '(不适用)',
                '{{expiration_date}}': '(不适用)',
            }
            subj, body = email_svc.render_template_body(tpl, ctx)
            ok, _ = email_svc.send_email(
                user['email'], subj, body,
                f"您好, {user.get('username', '用户')}!",
                '登录面板查看', panel_url,
            )
            if ok:
                success += 1
            else:
                errors += 1
            time.sleep(email_svc.get_email_delay())

        log_activity(actor, 'batch_email_users', '成功', f"批量邮件(用户)完成。成功: {success}, 失败: {errors}。")

    elif action == 'delete':
        for uid in user_ids:
            owned = PteroServer.query.filter_by(owner_id=uid).all()
            try:
                for srv in owned:
                    ptero.delete_server_from_panel(srv.id)
                db.session.expire_all()
                if ptero.delete_user_from_panel(uid):
                    success += 1
                else:
                    errors += 1
            except Exception:
                errors += 1

        log_activity(actor, 'batch_delete_users', '成功', f"批量删除用户完成。成功: {success}, 失败: {errors}。")

    else:
        return jsonify({'error': f'未知操作: {action}'}), 400

    return jsonify({'message': f'操作完成：成功 {success}，失败 {errors}', 'success': success, 'failed': errors})
