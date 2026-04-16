"""Settings routes — system config management."""

from flask import Blueprint, request, jsonify, session
from app.config import config_manager
from app.utils import log_activity
from app.services.email import send_email

bp = Blueprint('settings', __name__)


@bp.route('/settings')
def settings_get():
    cfg = dict(config_manager.config)
    cfg.pop('SECRET_KEY', None)
    cfg.pop('PTERO_DB_URI', None)
    for k in list(cfg.keys()):
        if any(s in k for s in ['KEY', 'PASSWORD']):
            cfg[k] = '********'
    return jsonify(cfg)


@bp.route('/settings', methods=['POST'])
def settings_save():
    data = request.get_json(silent=True) or {}
    actor = session.get('admin_username', '未知管理员')
    whitelist = config_manager.SETTINGS_WHITELIST

    settings_to_save = {}
    for key, value in data.items():
        if key not in whitelist:
            continue
        if value == '********':
            continue
        if any(s in key for s in ['KEY', 'PASSWORD']) and not value:
            continue
        settings_to_save[key] = value

    config_manager.save_config(settings_to_save)

    log_activity(actor, 'settings_change', '成功', '保存了系统设置。')
    return jsonify({'message': '设置已保存'})


@bp.route('/settings/test-email', methods=['POST'])
def test_email():
    """Send a test email to the configured sender address."""
    data = request.get_json(silent=True) or {}
    recipient = data.get('recipient', config_manager.get('SENDER_EMAIL'))
    if not recipient:
        return jsonify({'error': '没有指定收件地址且未配置发件人邮箱'}), 400

    ok, msg = send_email(
        recipient_email=recipient,
        subject='测试邮件 — 邮件服务配置成功',
        main_content_raw='这是一封测试邮件，用于验证 SMTP 配置是否正确。\n\n如果您能看到这封邮件，说明邮件服务已成功配置。',
        greeting='您好！',
    )
    if ok:
        return jsonify({'message': f'测试邮件已发送至 {recipient}'})
    return jsonify({'error': msg}), 500
