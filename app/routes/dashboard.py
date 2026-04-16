"""Dashboard route."""

from flask import Blueprint, jsonify
from app.models import PteroServer, PteroUser, ServerMeta
from app.config import config_manager
from app.utils import get_today

bp = Blueprint('dashboard', __name__)

APP_VERSION = '2.0.0'


@bp.route('/version')
def version():
    return jsonify({
        'version': APP_VERSION,
        'brandName': config_manager.get('BRAND_NAME', 'Ptero Manager'),
        'timezone': config_manager.get('TIMEZONE', 'Asia/Shanghai'),
    })


@bp.route('/dashboard')
def dashboard():
    total_users = PteroUser.query.count()
    all_servers = PteroServer.query.outerjoin(ServerMeta).all()
    total_servers = len(all_servers)

    counts = {'normal': 0, 'expiring_soon': 0, 'expired': 0, 'suspended': 0, 'permanent': 0}
    today = get_today()
    for s in all_servers:
        if s.is_suspended:
            counts['suspended'] += 1
        exp_date = s.expiration_date
        if exp_date is None:
            counts['permanent'] += 1
        else:
            days_left = (exp_date - today).days
            if days_left < 0:
                counts['expired'] += 1
            elif days_left <= 7:
                counts['expiring_soon'] += 1
            else:
                counts['normal'] += 1

    normal_count = counts['normal'] + counts['expiring_soon'] + counts['permanent']
    return jsonify({
        'totalUsers': total_users,
        'totalServers': total_servers,
        'normalCount': normal_count,
        'statusDistribution': counts,
    })
