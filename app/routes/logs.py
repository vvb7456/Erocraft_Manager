"""Activity logs route."""

import math
from flask import Blueprint, request, jsonify
from sqlalchemy import desc
from app.extensions import db
from app.models import ManagerActivityLog

bp = Blueprint('logs', __name__)


@bp.route('/activity-logs')
def activity_logs():
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(max(1, request.args.get('per_page', 30, type=int)), 100)

    query = ManagerActivityLog.query
    actor = request.args.get('actor')
    action = request.args.get('action')
    status = request.args.get('status')

    if actor:
        query = query.filter(ManagerActivityLog.actor == actor)
    if action:
        query = query.filter(ManagerActivityLog.action == action)
    if status:
        query = query.filter(ManagerActivityLog.status == status)

    query = query.order_by(desc(ManagerActivityLog.timestamp))
    total = query.count()
    logs = query.offset((page - 1) * per_page).limit(per_page).all()

    distinct_actors = [a[0] for a in db.session.query(ManagerActivityLog.actor).distinct().order_by(ManagerActivityLog.actor).all()]
    distinct_actions = [a[0] for a in db.session.query(ManagerActivityLog.action).distinct().order_by(ManagerActivityLog.action).all()]

    return jsonify({
        'logs': [{
            'id': log.id,
            'timestamp': log.timestamp.isoformat() if log.timestamp else None,
            'actor': log.actor,
            'action': log.action,
            'status': log.status,
            'details': log.details,
        } for log in logs],
        'total': total,
        'page': page,
        'perPage': per_page,
        'totalPages': math.ceil(total / per_page) if total > 0 else 1,
        'filters': {
            'actors': distinct_actors,
            'actions': distinct_actions,
        },
    })
