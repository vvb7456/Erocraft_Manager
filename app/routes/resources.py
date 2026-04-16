"""Resource proxy routes — nodes, nests, eggs (pass-through to Pterodactyl API)."""

from flask import Blueprint, jsonify
from app.services.pterodactyl import get_data
from app.config import config_manager

bp = Blueprint('resources', __name__)


@bp.route('/nests')
def list_nests():
    nests = get_data('nests')
    return jsonify({
        'nests': [n['attributes'] for n in nests] if nests else []
    })


@bp.route('/nodes')
def list_nodes():
    nodes = get_data('nodes')
    return jsonify({
        'nodes': [n['attributes'] for n in nodes] if nodes else []
    })


@bp.route('/resources/users')
def list_users_simple():
    """Lightweight user list for dropdowns (id + username + email)."""
    from app.models import PteroUser
    users = PteroUser.query.order_by(PteroUser.username).all()
    return jsonify({
        'users': [{'id': u.id, 'username': u.username, 'email': u.email} for u in users]
    })


@bp.route('/resources/server-defaults')
def server_defaults():
    """Return default values for the create-server form."""
    cfg = config_manager.config
    return jsonify({
        'nest_id': cfg.get('DEFAULT_NEST_ID', 1),
        'egg_id': cfg.get('DEFAULT_EGG_ID', 1),
        'node_id': cfg.get('DEFAULT_NODE_ID', 1),
        'docker_image': cfg.get('DOCKER_IMAGE', ''),
        'cpu': cfg.get('DEFAULT_CPU', 100),
        'memory': cfg.get('DEFAULT_MEMORY', 1024),
        'disk': cfg.get('DEFAULT_DISK', 5120),
        'databases': cfg.get('DEFAULT_DATABASES', 0),
        'backups': cfg.get('DEFAULT_BACKUPS', 0),
        'allocations': cfg.get('DEFAULT_ALLOCATIONS', 1),
        'server_name_prefix': cfg.get('SERVER_NAME_PREFIX', ''),
    })


@bp.route('/nodes/<int:node_id>/allocations')
def node_allocations(node_id):
    allocs = get_data(f"nodes/{node_id}/allocations")
    unassigned = [
        a['attributes'] for a in allocs
        if a.get('attributes') and not a['attributes'].get('assigned')
    ] if allocs else []
    return jsonify({'allocations': unassigned})


@bp.route('/nests/<int:nest_id>/eggs')
def nest_eggs(nest_id):
    eggs_data = get_data(f"nests/{nest_id}/eggs")
    return jsonify({
        'eggs': [e['attributes'] for e in eggs_data] if eggs_data else []
    })


@bp.route('/nests/<int:nest_id>/eggs/<int:egg_id>/variables')
def egg_variables(nest_id, egg_id):
    egg_data_list = get_data(f"nests/{nest_id}/eggs/{egg_id}?include=variables")
    if not egg_data_list:
        return jsonify({'error': 'Egg not found'}), 404
    variables = (
        egg_data_list[0]
        .get('attributes', {})
        .get('relationships', {})
        .get('variables', {})
        .get('data', [])
    )
    return jsonify({'variables': [v['attributes'] for v in variables]})
