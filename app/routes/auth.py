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

    session.clear()
    session['user_id'] = user.id
    session['username'] = user.username
    session['is_admin'] = bool(user.root_admin)
    session.permanent = True
    log_activity(user.username, 'login', '成功', f"用户 {user.username} 成功登录。")
    return jsonify({'ok': True, 'username': user.username, 'is_admin': bool(user.root_admin)})


@bp.route('/me')
def me():
    if session.get('user_id'):
        return jsonify({
            'ok': True,
            'username': session.get('username', ''),
            'is_admin': session.get('is_admin', False),
        })
    return jsonify({'ok': False}), 401


@bp.route('/logout', methods=['POST'])
def logout():
    username = session.get('username', '未知用户')
    session.clear()
    log_activity(username, 'logout', '信息', f"用户 {username} 退出登录。")
    return jsonify({'ok': True})
