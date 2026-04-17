"""Wings daemon direct API client.

Decrypts daemon_token from Panel DB using APP_KEY,
then calls Wings HTTP API or signs JWT for WebSocket.
"""

import base64
import json
import re
import uuid as _uuid
import time
from functools import lru_cache

import jwt
import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from flask import current_app

from app.config import config_manager
from app.extensions import db


# ── Token decryption ──

def _get_app_key() -> bytes:
    raw = config_manager.get('PANEL_APP_KEY') or ''
    if raw.startswith('base64:'):
        return base64.b64decode(raw[7:])
    return raw.encode()


def decrypt_laravel(encrypted_b64: str, app_key: bytes) -> str:
    """Decrypt a Laravel AES-256-CBC encrypted value."""
    payload = json.loads(base64.b64decode(encrypted_b64))
    iv = base64.b64decode(payload['iv'])
    value = base64.b64decode(payload['value'])
    cipher = Cipher(algorithms.AES(app_key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    decrypted = decryptor.update(value) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(decrypted) + unpadder.finalize()
    m = re.match(rb's:\d+:"(.+)";', plaintext)
    return m.group(1).decode() if m else plaintext.decode()


# ── Node info cache ──

_node_cache: dict[int, dict] = {}


def _get_node_info(node_id: int) -> dict:
    """Get node connection info (cached per process lifetime)."""
    if node_id in _node_cache:
        return _node_cache[node_id]

    row = db.session.execute(db.text(
        'SELECT fqdn, scheme, daemonListen, daemon_token FROM nodes WHERE id = :nid'
    ), {'nid': node_id}).first()

    if not row:
        raise ValueError(f'Node {node_id} not found')

    token = decrypt_laravel(row.daemon_token, _get_app_key())
    info = {
        'fqdn': row.fqdn,
        'scheme': row.scheme,
        'port': row.daemonListen,
        'token': token,
    }
    _node_cache[node_id] = info
    return info


def clear_node_cache():
    """Clear cached node info (call after node config changes)."""
    _node_cache.clear()


def _base_url(node: dict) -> str:
    return f"{node['scheme']}://{node['fqdn']}:{node['port']}"


def _headers(node: dict) -> dict:
    return {
        'Authorization': f"Bearer {node['token']}",
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }


# ── WebSocket JWT ──

def create_ws_token(node_id: int, server_uuid: str, user_uuid: str) -> dict:
    """Create a signed JWT for Wings WebSocket + return socket URL."""
    node = _get_node_info(node_id)
    now = int(time.time())
    token = jwt.encode({
        'server_uuid': server_uuid,
        'permissions': [
            '*',
            'admin.websocket.errors',
            'admin.websocket.install',
            'admin.websocket.transfer',
        ],
        'user_uuid': user_uuid,
        'unique_id': str(_uuid.uuid4()),
        'iat': now,
        'nbf': now,
        'exp': now + 600,
    }, node['token'], algorithm='HS256')

    ws_scheme = 'wss' if node['scheme'] == 'https' else 'ws'
    socket_url = f"{ws_scheme}://{node['fqdn']}:{node['port']}/api/servers/{server_uuid}/ws"

    return {'token': token, 'socket': socket_url}


# ── Server operations ──

def get_server_resources(node_id: int, server_uuid: str) -> dict | None:
    """Get server state + resource utilization from Wings."""
    node = _get_node_info(node_id)
    url = f"{_base_url(node)}/api/servers/{server_uuid}"
    resp = requests.get(url, headers=_headers(node), timeout=10)
    if resp.ok:
        return resp.json()
    return None


def send_power_action(node_id: int, server_uuid: str, action: str) -> bool:
    """Send power action (start/stop/restart/kill) to a server."""
    if action not in ('start', 'stop', 'restart', 'kill'):
        raise ValueError(f'Invalid power action: {action}')
    node = _get_node_info(node_id)
    url = f"{_base_url(node)}/api/servers/{server_uuid}/power"
    resp = requests.post(url, headers=_headers(node), json={'action': action}, timeout=10)
    return resp.ok


def send_command(node_id: int, server_uuid: str, command: str) -> bool:
    """Send a command to a running server's stdin."""
    node = _get_node_info(node_id)
    url = f"{_base_url(node)}/api/servers/{server_uuid}/commands"
    resp = requests.post(url, headers=_headers(node), json={'command': command}, timeout=10)
    return resp.ok


# ── File operations ──

def list_files(node_id: int, server_uuid: str, directory: str = '/') -> list | None:
    node = _get_node_info(node_id)
    url = f"{_base_url(node)}/api/servers/{server_uuid}/files/list-directory"
    resp = requests.get(url, headers=_headers(node), params={'directory': directory}, timeout=15)
    if resp.ok:
        return resp.json()
    return None


def get_file_contents(node_id: int, server_uuid: str, file_path: str) -> str | None:
    node = _get_node_info(node_id)
    url = f"{_base_url(node)}/api/servers/{server_uuid}/files/contents"
    resp = requests.get(url, headers=_headers(node), params={'file': file_path}, timeout=15)
    if resp.ok:
        return resp.text
    return None


def write_file(node_id: int, server_uuid: str, file_path: str, content: str) -> bool:
    node = _get_node_info(node_id)
    url = f"{_base_url(node)}/api/servers/{server_uuid}/files/write"
    resp = requests.post(
        url, params={'file': file_path},
        headers={**_headers(node), 'Content-Type': 'text/plain'},
        data=content.encode('utf-8'), timeout=15,
    )
    return resp.ok


def rename_file(node_id: int, server_uuid: str, root: str, rename_from: str, rename_to: str) -> bool:
    node = _get_node_info(node_id)
    url = f"{_base_url(node)}/api/servers/{server_uuid}/files/rename"
    resp = requests.put(url, headers=_headers(node), json={
        'root': root,
        'files': [{'from': rename_from, 'to': rename_to}],
    }, timeout=10)
    return resp.ok


def delete_files(node_id: int, server_uuid: str, root: str, files: list[str]) -> bool:
    node = _get_node_info(node_id)
    url = f"{_base_url(node)}/api/servers/{server_uuid}/files/delete"
    resp = requests.post(url, headers=_headers(node), json={
        'root': root, 'files': files,
    }, timeout=15)
    return resp.ok


def create_directory(node_id: int, server_uuid: str, name: str, path: str) -> bool:
    node = _get_node_info(node_id)
    url = f"{_base_url(node)}/api/servers/{server_uuid}/files/create-directory"
    resp = requests.post(url, headers=_headers(node), json={
        'name': name, 'path': path,
    }, timeout=10)
    return resp.ok


def compress_files(node_id: int, server_uuid: str, root: str, files: list[str]) -> dict | None:
    node = _get_node_info(node_id)
    url = f"{_base_url(node)}/api/servers/{server_uuid}/files/compress"
    resp = requests.post(url, headers=_headers(node), json={
        'root': root, 'files': files,
    }, timeout=60)
    if resp.ok:
        return resp.json()
    return None


def decompress_file(node_id: int, server_uuid: str, root: str, file_path: str) -> bool:
    node = _get_node_info(node_id)
    url = f"{_base_url(node)}/api/servers/{server_uuid}/files/decompress"
    resp = requests.post(url, headers=_headers(node), json={
        'root': root, 'file': file_path,
    }, timeout=60)
    return resp.ok


def get_download_url(node_id: int, server_uuid: str, file_path: str) -> str | None:
    """Get a signed one-time download URL from Wings."""
    node = _get_node_info(node_id)
    # Wings download uses a JWT token in query param
    now = int(time.time())
    token = jwt.encode({
        'server_uuid': server_uuid,
        'file_path': file_path,
        'unique_id': str(_uuid.uuid4()),
        'iat': now,
        'nbf': now,
        'exp': now + 300,
    }, node['token'], algorithm='HS256')
    return f"{_base_url(node)}/download/file?token={token}"


def get_upload_url(node_id: int, server_uuid: str) -> str | None:
    """Get a signed upload URL from Wings."""
    node = _get_node_info(node_id)
    now = int(time.time())
    token = jwt.encode({
        'server_uuid': server_uuid,
        'unique_id': str(_uuid.uuid4()),
        'iat': now,
        'nbf': now,
        'exp': now + 900,
    }, node['token'], algorithm='HS256')
    return f"{_base_url(node)}/upload/file?token={token}"


# ── System info ──

def get_system_info(node_id: int) -> dict | None:
    """Get Wings node system information."""
    node = _get_node_info(node_id)
    url = f"{_base_url(node)}/api/system"
    resp = requests.get(url, headers=_headers(node), timeout=10)
    if resp.ok:
        return resp.json()
    return None
