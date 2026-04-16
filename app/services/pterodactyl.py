"""Pterodactyl Application API client — write operations only.

Server/user listing is now done via direct MySQL queries (see models.py).
This module retains API calls for: create/delete/suspend/unsuspend servers,
create/update/delete users, and fetching nests/eggs/nodes/allocations.
"""

import re
import requests
from datetime import timedelta
from flask import current_app
from app.extensions import db
from app.models import ServerMeta
from app.config import config_manager


# ── Helpers ──

def _panel_url() -> str:
    return (config_manager.get('PTERO_PANEL_URL') or '').rstrip('/')


def _api_headers() -> dict:
    return {
        'Authorization': f"Bearer {config_manager.get('PTERO_API_KEY')}",
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }


def _check_configured():
    """Raise ValueError if panel URL or API key is missing."""
    if not _panel_url() or not config_manager.get('PTERO_API_KEY'):
        raise ValueError('Pterodactyl API 未配置')


# ── Generic data fetchers (kept for nests/eggs/nodes/allocations) ──

def get_data(endpoint: str, params: dict | None = None) -> list | None:
    """Fetch all pages from a Pterodactyl Application API list endpoint.

    Returns a list of raw item dicts (each containing 'attributes'), or None on error.
    """
    _check_configured()
    all_items: list = []
    page = 1
    base_url = f"{_panel_url()}/api/application/{endpoint}"
    headers = _api_headers()
    is_single = bool(re.search(r'/\d+(\?|$)', endpoint))

    while True:
        try:
            query_params = {'page': page, 'per_page': 100}
            if params:
                query_params.update(params)
            final_params = query_params if not is_single else params
            res = requests.get(base_url, headers=headers, params=final_params, timeout=15)
            res.raise_for_status()
            data = res.json()

            if data.get('object') != 'list':
                return [data] if 'attributes' in data else []

            current_items = data.get('data', [])
            if not current_items:
                break
            all_items.extend(current_items)

            meta = data.get('meta', {}).get('pagination', {})
            cp = meta.get('current_page')
            tp = meta.get('total_pages')
            if is_single or cp is None or tp is None or cp >= tp:
                break
            page += 1
        except requests.RequestException as e:
            current_app.logger.error(f"Error fetching {endpoint}: {e}")
            return None

    return all_items


def get_single(endpoint: str):
    """Fetch a single resource's attributes dict, or None on error."""
    _check_configured()
    try:
        res = requests.get(
            f"{_panel_url()}/api/application/{endpoint}",
            headers=_api_headers(), timeout=10,
        )
        res.raise_for_status()
        return res.json().get('attributes')
    except requests.RequestException:
        return None


# ── Server operations ──

def suspend_server(ptero_id: int) -> bool:
    try:
        res = requests.post(f"{_panel_url()}/api/application/servers/{ptero_id}/suspend",
                            headers=_api_headers(), timeout=20)
        res.raise_for_status()
        return True
    except requests.RequestException:
        return False


def unsuspend_server(ptero_id: int) -> bool:
    try:
        res = requests.post(f"{_panel_url()}/api/application/servers/{ptero_id}/unsuspend",
                            headers=_api_headers(), timeout=20)
        res.raise_for_status()
        return True
    except requests.RequestException:
        return False


def delete_server_from_panel(ptero_id: int) -> bool:
    try:
        res = requests.delete(f"{_panel_url()}/api/application/servers/{ptero_id}",
                              headers=_api_headers(), timeout=20)
        if res.status_code not in (204, 404):
            res.raise_for_status()
        return True
    except requests.RequestException:
        return False


def create_server(user_id: int, server_name: str, expiration_days: int,
                  node_id: int, allocation_id: int, egg_id: int, docker_image: str,
                  startup_command: str, environment: dict,
                  cpu: int, memory: int, disk: int,
                  databases: int, backups: int, allocations: int):
    """Create a server via the Pterodactyl API and store its expiration meta.

    Returns the server attributes dict on success, or None.
    """
    from app.utils import get_today
    expiration_date = get_today() + timedelta(days=expiration_days)
    description = f"到期时间：{expiration_date.strftime('%Y/%m/%d')}"
    payload = {
        'name': server_name, 'user': user_id, 'egg': egg_id,
        'description': description, 'docker_image': docker_image,
        'startup': startup_command, 'environment': environment,
        'limits': {'memory': memory, 'swap': 0, 'disk': disk, 'io': 500, 'cpu': cpu},
        'feature_limits': {'databases': databases, 'allocations': allocations, 'backups': backups},
        'allocation': {'default': allocation_id},
    }
    try:
        res = requests.post(f"{_panel_url()}/api/application/servers",
                            headers=_api_headers(), json=payload, timeout=20)
        res.raise_for_status()
        server_data = res.json().get('attributes')

        # Store expiration in our custom meta table
        meta = ServerMeta(server_id=server_data['id'], expiration_date=expiration_date)
        db.session.add(meta)
        db.session.commit()

        return server_data
    except requests.RequestException as e:
        current_app.logger.error(f"创建服务器失败: {e}")
        return None


def update_server_description(ptero_id: int, new_expiration_date) -> bool:
    """Update the expiration date line in a server's Pterodactyl description."""
    try:
        server_data = get_single(f"servers/{ptero_id}")
        if not server_data:
            return False

        old_desc = server_data.get('description', '') or ''
        new_line = f"到期时间：{new_expiration_date.strftime('%Y/%m/%d')}"
        # Replace existing line or append
        new_desc = re.sub(r'到期时间[：:]\s*\d{4}[/-]\d{1,2}[/-]\d{1,2}', new_line, old_desc)
        if new_line not in new_desc:
            new_desc = f"{new_line}\n{old_desc}".strip()

        payload = {
            'name': server_data['name'],
            'user': server_data['user'],
            'description': new_desc,
        }
        res = requests.patch(f"{_panel_url()}/api/application/servers/{ptero_id}/details",
                             headers=_api_headers(), json=payload, timeout=20)
        res.raise_for_status()
        return True
    except requests.RequestException as e:
        current_app.logger.error(f"更新服务器描述失败 (ID {ptero_id}): {e}")
        return False


# ── User operations ──

def create_user(email: str, username: str):
    """Create a user via the Pterodactyl API. Returns attributes dict or None."""
    payload = {
        'email': email, 'username': username,
        'first_name': 'New', 'last_name': 'User', 'root_admin': False,
    }
    try:
        res = requests.post(f"{_panel_url()}/api/application/users",
                            headers=_api_headers(), json=payload, timeout=20)
        if res.status_code == 422:
            errors = res.json().get('errors', [])
            msg = '; '.join(e.get('detail', '') for e in errors) if errors else '验证失败'
            return None, msg
        res.raise_for_status()
        return res.json().get('attributes'), None
    except requests.RequestException as e:
        return None, str(e)


def update_user(user_id: int, payload: dict):
    """PATCH a user via the Pterodactyl API.

    Returns (attributes_dict, None) on success, or (None, error_message) on failure.
    """
    url = f"{_panel_url()}/api/application/users/{user_id}"
    try:
        res = requests.patch(url, headers=_api_headers(), json=payload, timeout=20)
        if res.status_code == 422:
            errors = res.json().get('errors', [])
            msg = '; '.join(e.get('detail', '') for e in errors) if errors else '验证失败'
            return None, msg
        res.raise_for_status()
        return res.json().get('attributes'), None
    except requests.RequestException as e:
        return None, str(e)


def delete_user_from_panel(user_id: int) -> bool:
    try:
        res = requests.delete(f"{_panel_url()}/api/application/users/{user_id}",
                              headers=_api_headers(), timeout=20)
        if res.status_code not in (204, 404):
            res.raise_for_status()
        return True
    except requests.RequestException:
        return False
