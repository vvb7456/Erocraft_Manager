"""Automation settings routes."""

from flask import Blueprint, request, jsonify, session
import pytz
from app.config import config_manager
from app.utils import log_activity
from app.services.scheduler import reload_jobs

bp = Blueprint('automation', __name__)


def _clamp_int(val, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(val)))
    except (TypeError, ValueError):
        return default


@bp.route('/automation')
def automation_get():
    keys = [
        'AUTOMATION_RUN_HOUR', 'AUTOMATION_RUN_MINUTE',
        'AUTOMATION_SUSPEND_ENABLED', 'AUTOMATION_DELETE_ENABLED', 'AUTOMATION_DELETE_DAYS',
        'AUTOMATION_EMAIL_ENABLED', 'AUTOMATION_EMAIL_RUN_HOUR', 'AUTOMATION_EMAIL_RUN_MINUTE',
        'TIMEZONE',
    ]
    return jsonify({k: config_manager.get(k) for k in keys})


@bp.route('/automation', methods=['POST'])
def automation_save():
    data = request.get_json(silent=True) or {}
    actor = session.get('username', '未知管理员')

    automation_settings = {
        'AUTOMATION_RUN_HOUR': _clamp_int(data.get('AUTOMATION_RUN_HOUR'), 0, 23, 2),
        'AUTOMATION_RUN_MINUTE': _clamp_int(data.get('AUTOMATION_RUN_MINUTE'), 0, 59, 0),
        'AUTOMATION_DELETE_DAYS': _clamp_int(data.get('AUTOMATION_DELETE_DAYS'), 0, 365, 14),
        'AUTOMATION_EMAIL_RUN_HOUR': _clamp_int(data.get('AUTOMATION_EMAIL_RUN_HOUR'), 0, 23, 10),
        'AUTOMATION_EMAIL_RUN_MINUTE': _clamp_int(data.get('AUTOMATION_EMAIL_RUN_MINUTE'), 0, 59, 0),
        'AUTOMATION_SUSPEND_ENABLED': bool(data.get('AUTOMATION_SUSPEND_ENABLED', False)),
        'AUTOMATION_DELETE_ENABLED': bool(data.get('AUTOMATION_DELETE_ENABLED', False)),
        'AUTOMATION_EMAIL_ENABLED': bool(data.get('AUTOMATION_EMAIL_ENABLED', False)),
    }

    tz_input = data.get('TIMEZONE', 'Asia/Shanghai')
    try:
        pytz.timezone(tz_input)
        automation_settings['TIMEZONE'] = tz_input
    except pytz.exceptions.UnknownTimeZoneError:
        return jsonify({'error': f'无效的时区: {tz_input}'}), 400

    config_manager.save_config(automation_settings)
    reload_jobs()
    log_activity(actor, 'automation_settings_change', '成功', '保存了自动化设置，计划任务已热更新。')
    return jsonify({'message': '自动化设置已保存。'})
