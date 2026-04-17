"""User-facing file management API — proxies to Wings."""

from functools import wraps
from flask import Blueprint, session, jsonify, request, abort
from app.models import PteroServer
from app.services import wings

bp = Blueprint('user_files', __name__)


def require_server(f):
    """Decorator: load server and verify ownership."""
    @wraps(f)
    def decorated(server_id, *args, **kwargs):
        server = PteroServer.query.get_or_404(server_id)
        if server.owner_id != session['user_id']:
            abort(403)
        return f(server, *args, **kwargs)
    return decorated


@bp.route('/servers/<int:server_id>/files/list')
@require_server
def list_files(server):
    directory = request.args.get('directory', '/')
    data = wings.list_files(server.node_id, server.uuid, directory)
    if data is None:
        return jsonify({'error': 'Failed to list files'}), 502
    return jsonify(data)


@bp.route('/servers/<int:server_id>/files/contents')
@require_server
def get_file_contents(server):
    file_path = request.args.get('file', '')
    if not file_path:
        return jsonify({'error': 'file parameter required'}), 400
    content = wings.get_file_contents(server.node_id, server.uuid, file_path)
    if content is None:
        return jsonify({'error': 'Failed to read file'}), 502
    return jsonify({'content': content})


@bp.route('/servers/<int:server_id>/files/write', methods=['POST'])
@require_server
def write_file(server):
    file_path = request.args.get('file', '')
    if not file_path:
        return jsonify({'error': 'file parameter required'}), 400
    body = request.get_json(silent=True) or {}
    content = body.get('content', '')
    ok = wings.write_file(server.node_id, server.uuid, file_path, content)
    if not ok:
        return jsonify({'error': 'Failed to write file'}), 502
    return '', 204


@bp.route('/servers/<int:server_id>/files/rename', methods=['POST'])
@require_server
def rename_file(server):
    body = request.get_json(silent=True) or {}
    root = body.get('root', '/')
    rename_from = body.get('from', '')
    rename_to = body.get('to', '')
    if not rename_from or not rename_to:
        return jsonify({'error': 'from and to required'}), 400
    ok = wings.rename_file(server.node_id, server.uuid, root, rename_from, rename_to)
    if not ok:
        return jsonify({'error': 'Failed to rename'}), 502
    return '', 204


@bp.route('/servers/<int:server_id>/files/delete', methods=['POST'])
@require_server
def delete_files(server):
    body = request.get_json(silent=True) or {}
    root = body.get('root', '/')
    files = body.get('files', [])
    if not files:
        return jsonify({'error': 'files list required'}), 400
    ok = wings.delete_files(server.node_id, server.uuid, root, files)
    if not ok:
        return jsonify({'error': 'Failed to delete'}), 502
    return '', 204


@bp.route('/servers/<int:server_id>/files/compress', methods=['POST'])
@require_server
def compress_files(server):
    body = request.get_json(silent=True) or {}
    root = body.get('root', '/')
    files = body.get('files', [])
    if not files:
        return jsonify({'error': 'files list required'}), 400
    result = wings.compress_files(server.node_id, server.uuid, root, files)
    if result is None:
        return jsonify({'error': 'Failed to compress'}), 502
    return jsonify(result)


@bp.route('/servers/<int:server_id>/files/decompress', methods=['POST'])
@require_server
def decompress_file(server):
    body = request.get_json(silent=True) or {}
    root = body.get('root', '/')
    file_path = body.get('file', '')
    if not file_path:
        return jsonify({'error': 'file required'}), 400
    ok = wings.decompress_file(server.node_id, server.uuid, root, file_path)
    if not ok:
        return jsonify({'error': 'Failed to decompress'}), 502
    return '', 204


@bp.route('/servers/<int:server_id>/files/create-folder', methods=['POST'])
@require_server
def create_folder(server):
    body = request.get_json(silent=True) or {}
    name = body.get('name', '')
    path = body.get('path', '/')
    if not name:
        return jsonify({'error': 'name required'}), 400
    ok = wings.create_directory(server.node_id, server.uuid, name, path)
    if not ok:
        return jsonify({'error': 'Failed to create folder'}), 502
    return '', 204


@bp.route('/servers/<int:server_id>/files/download')
@require_server
def download_file(server):
    file_path = request.args.get('file', '')
    if not file_path:
        return jsonify({'error': 'file parameter required'}), 400
    url = wings.get_download_url(server.node_id, server.uuid, file_path)
    if not url:
        return jsonify({'error': 'Failed to get download URL'}), 502
    return jsonify({'url': url})


@bp.route('/servers/<int:server_id>/files/upload', methods=['POST'])
@require_server
def upload_url(server):
    url = wings.get_upload_url(server.node_id, server.uuid)
    if not url:
        return jsonify({'error': 'Failed to get upload URL'}), 502
    return jsonify({'url': url})
