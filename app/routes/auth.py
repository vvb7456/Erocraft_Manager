"""Auth routes — login, logout, session check (Pterodactyl DB)."""

from flask import Blueprint, request, jsonify, session, current_app
from app.models import PteroUser
from app.utils import log_activity

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'ok': False, 'error': '用户名或密码不能为空'}), 400

    # Look up by username or email
    user = PteroUser.query.filter(
        (PteroUser.username == username) | (PteroUser.email == username)
    ).first()

    if not user or not user.check_password(password):
        log_activity(username or '未知', 'login', '失败', f"尝试使用 {username} 登录失败。")
        return jsonify({'ok': False, 'error': '用户名或密码无效'}), 401

    if not user.root_admin:
        log_activity(user.username, 'login', '失败', f"用户 {user.username} 非管理员，拒绝登录。")
        return jsonify({'ok': False, 'error': '该用户不是管理员，无权访问'}), 403

    session.clear()
    session['admin_user_id'] = user.id
    session['admin_username'] = user.username
    session.permanent = True
    log_activity(user.username, 'login', '成功', f"用户 {user.username} 成功登录。")
    return jsonify({'ok': True, 'username': user.username})


@bp.route('/me')
def me():
    if session.get('admin_user_id'):
        return jsonify({
            'ok': True,
            'username': session.get('admin_username', ''),
        })
    return jsonify({'ok': False}), 401


@bp.route('/logout', methods=['POST'])
def logout():
    username = session.get('admin_username', '未知用户')
    session.clear()
    log_activity(username, 'logout', '信息', f"用户 {username} 退出登录。")
    return jsonify({'ok': True})
