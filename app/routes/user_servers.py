"""User-facing server API routes — server list, details, power, console."""

from functools import wraps
from flask import Blueprint, session, jsonify, request, abort
from app.extensions import db
from app.models import PteroServer
from app.services import wings

bp = Blueprint('user_servers', __name__)


def require_server(f):
    """Decorator: load server and verify ownership."""
    @wraps(f)
    def decorated(server_id, *args, **kwargs):
        server = PteroServer.query.get_or_404(server_id)
        if server.owner_id != session['user_id']:
            abort(403)
        return f(server, *args, **kwargs)
    return decorated


@bp.route('/servers')
def list_servers():
    """List current user's servers with allocation info."""
    user_id = session['user_id']
    rows = db.session.execute(db.text('''
        SELECT s.id, s.uuid, s.uuidShort, s.name, s.description, s.status, s.installed_at,
               s.node_id, s.egg_id, s.memory, s.disk, s.cpu,
               a.ip, a.ip_alias, a.port,
               n.fqdn, n.scheme, n.daemonListen,
               m.expiration_date
        FROM servers s
        LEFT JOIN allocations a ON a.id = s.allocation_id
        LEFT JOIN nodes n ON n.id = s.node_id
        LEFT JOIN manager_server_meta m ON m.server_id = s.id
        WHERE s.owner_id = :uid
        ORDER BY s.created_at DESC
    '''), {'uid': user_id}).fetchall()

    servers = []
    for r in rows:
        exp = str(r.expiration_date) if r.expiration_date else None
        days_left = None
        if r.expiration_date:
            from datetime import date
            days_left = (r.expiration_date - date.today()).days

        servers.append({
            'id': r.id,
            'uuid': r.uuid,
            'uuidShort': r.uuidShort,
            'name': r.name,
            'description': r.description,
            'status': r.status,
            'isInstalling': r.status == 'installing' or r.installed_at is None,
            'isInstalled': r.installed_at is not None and r.status != 'installing',
            'isSuspended': r.status == 'suspended',
            'nodeId': r.node_id,
            'eggId': r.egg_id,
            'limits': {
                'memory': r.memory,
                'disk': r.disk,
                'cpu': r.cpu,
            },
            'allocation': {
                'ip': r.ip_alias or r.ip,
                'port': r.port,
            },
            'node': {
                'fqdn': r.fqdn,
            },
            'expirationDate': exp,
            'daysLeft': days_left,
            'address': f"{r.fqdn}:{r.port}" if r.fqdn and r.port else None,
        })

    return jsonify(servers)


@bp.route('/servers/<int:server_id>')
@require_server
def server_detail(server):
    """Get full server details including startup variables."""
    alloc = db.session.execute(db.text(
        'SELECT ip, ip_alias, port FROM allocations WHERE id = :aid'
    ), {'aid': server.allocation_id}).first()

    node = db.session.execute(db.text(
        'SELECT fqdn, scheme, daemonListen FROM nodes WHERE id = :nid'
    ), {'nid': server.node_id}).first()

    exp = None
    days_left = None
    if server.meta and server.meta.expiration_date:
        from datetime import date
        exp = str(server.meta.expiration_date)
        days_left = (server.meta.expiration_date - date.today()).days

    return jsonify({
        'id': server.id,
        'uuid': server.uuid,
        'uuidShort': server.uuidShort,
        'name': server.name,
        'description': server.description,
        'status': server.status,
        'isInstalling': server.status == 'installing' or server.installed_at is None,
        'isInstalled': server.installed_at is not None and server.status != 'installing',
        'isSuspended': server.is_suspended,
        'nodeId': server.node_id,
        'eggId': server.egg_id,
        'limits': {
            'memory': server.memory,
            'disk': server.disk,
            'cpu': server.cpu,
        },
        'allocation': {
            'ip': alloc.ip_alias or alloc.ip if alloc else None,
            'port': alloc.port if alloc else None,
        },
        'node': {
            'fqdn': node.fqdn if node else None,
        },
        'expirationDate': exp,
        'daysLeft': days_left,
        'address': f"{node.fqdn}:{alloc.port}" if node and alloc else None,
    })


@bp.route('/servers/<int:server_id>/resources')
@require_server
def server_resources(server):
    """Get real-time server resources from Wings."""
    data = wings.get_server_resources(server.node_id, server.uuid)
    if not data:
        return jsonify({'error': 'Failed to reach Wings'}), 502
    return jsonify({
        'state': data.get('state', 'offline'),
        'isSuspended': data.get('is_suspended', False),
        'resources': data.get('utilization', {}),
    })


@bp.route('/servers/<int:server_id>/power', methods=['POST'])
@require_server
def server_power(server):
    """Send power action to server."""
    body = request.get_json(silent=True) or {}
    action = body.get('action')
    if action not in ('start', 'stop', 'restart', 'kill'):
        return jsonify({'error': 'Invalid action'}), 400
    if server.is_suspended:
        return jsonify({'error': 'Server is suspended'}), 403

    ok = wings.send_power_action(server.node_id, server.uuid, action)
    if not ok:
        return jsonify({'error': 'Failed to send power action'}), 502
    return '', 204


@bp.route('/servers/<int:server_id>/command', methods=['POST'])
@require_server
def server_command(server):
    """Send command to server stdin."""
    body = request.get_json(silent=True) or {}
    command = body.get('command', '').strip()
    if not command:
        return jsonify({'error': 'Empty command'}), 400

    ok = wings.send_command(server.node_id, server.uuid, command)
    if not ok:
        return jsonify({'error': 'Failed to send command'}), 502
    return '', 204


@bp.route('/servers/<int:server_id>/console')
@require_server
def server_console(server):
    """Get WebSocket token + URL for console connection."""
    user = db.session.execute(db.text(
        'SELECT uuid FROM users WHERE id = :uid'
    ), {'uid': session['user_id']}).first()

    data = wings.create_ws_token(server.node_id, server.uuid, user.uuid)
    return jsonify(data)


@bp.route('/servers/<int:server_id>/startup')
@require_server
def server_startup(server):
    """Get startup variables with friendly labels."""
    rows = db.session.execute(db.text('''
        SELECT ev.env_variable, ev.name, ev.description, ev.default_value,
               ev.user_viewable, ev.user_editable, ev.rules,
               sv.variable_value
        FROM egg_variables ev
        LEFT JOIN server_variables sv ON sv.variable_id = ev.id AND sv.server_id = :sid
        WHERE ev.egg_id = :eid
        ORDER BY ev.id
    '''), {'sid': server.id, 'eid': server.egg_id}).fetchall()

    variables = []
    for r in rows:
        if not r.user_viewable:
            continue
        variables.append({
            'envVariable': r.env_variable,
            'name': r.name,
            'description': r.description,
            'defaultValue': r.default_value,
            'value': r.variable_value if r.variable_value is not None else r.default_value,
            'isEditable': bool(r.user_editable),
            'rules': r.rules,
        })

    return jsonify(variables)
