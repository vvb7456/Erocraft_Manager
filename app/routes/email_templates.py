"""Email template routes."""

from flask import Blueprint, request, jsonify, session
from app.services.email import load_all_templates, load_template, save_template
from app.utils import log_activity

bp = Blueprint('email_templates', __name__)

# Map from API type names to internal template types
_TYPE_MAP = {
    'bulk': 'bulk',
    'reminder': 'reminder',
    'preDelete': 'pre_delete',
    'createUser': 'create_user',
}

_LOG_LABELS = {
    'bulk': '批量邮件模板',
    'reminder': '到期提醒模板',
    'preDelete': '删除前提醒模板',
    'createUser': '新用户通知模板',
}


@bp.route('/email-templates')
def templates_get():
    all_t = load_all_templates()
    return jsonify({
        'bulk': all_t.get('bulk', {}),
        'reminder': all_t.get('reminder', {}),
        'preDelete': all_t.get('pre_delete', {}),
        'createUser': all_t.get('create_user', {}),
    })


@bp.route('/email-templates', methods=['POST'])
def templates_save():
    data = request.get_json(silent=True) or {}
    form_type = data.get('type')
    actor = session.get('username', '未知管理员')

    if form_type not in _TYPE_MAP:
        return jsonify({'error': '未知模板类型'}), 400

    internal_type = _TYPE_MAP[form_type]
    template_data = {'subject': data.get('subject', ''), 'body': data.get('body', '')}

    save_template(internal_type, template_data)
    log_activity(actor, 'email_template_change', '成功', f"保存了{_LOG_LABELS[form_type]}。")
    return jsonify({'message': '模板已保存'})
