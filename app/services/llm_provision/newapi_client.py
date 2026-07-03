"""NewAPI management API client.

Wraps the NewAPI HTTP API for token CRUD and usage queries. All requests
use short-lived ``httpx.AsyncClient`` instances with ``trust_env=False``
(consistent with ``agent_client.py`` / ``wings.py`` patterns).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
_MAX_RETRIES = 5
_RETRY_BASE_DELAY = 2.0  # seconds; doubles on each retry


class NewApiError(Exception):
    """Raised when a NewAPI management API call fails."""


class NewApiNotConfigured(NewApiError):
    """Raised when LLM/NewAPI settings are missing or incomplete."""


async def _read_llm_settings(db: Any) -> dict[str, Any]:
    """Load all LLM runtime settings from the settings store."""
    from app.core.runtime_settings import LLM_SPECS, defaults_for
    from app.core.settings_store import get_settings_store

    return await get_settings_store().get_many(db, defaults_for(LLM_SPECS))


def _check_configured(settings: dict[str, Any]) -> None:
    base_url = str(settings.get("NEWAPI_BASE_URL", "")).rstrip("/")
    admin_token = str(settings.get("NEWAPI_ADMIN_TOKEN", ""))
    pool_token = str(settings.get("NEWAPI_POOL_USER_ACCESS_TOKEN", ""))
    pool_user_id = int(settings.get("NEWAPI_POOL_USER_ID", 0) or 0)
    if not base_url or not admin_token:
        raise NewApiNotConfigured("NEWAPI_BASE_URL or NEWAPI_ADMIN_TOKEN not set")
    if not pool_token or pool_user_id == 0:
        raise NewApiNotConfigured(
            "NEWAPI_POOL_USER_ACCESS_TOKEN or NEWAPI_POOL_USER_ID not set"
        )


def _pool_user_headers(settings: dict[str, Any]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings['NEWAPI_POOL_USER_ACCESS_TOKEN']}",
        "New-Api-User": str(settings.get("NEWAPI_POOL_USER_ID", 0)),
        "Content-Type": "application/json",
    }


def _base_url(settings: dict[str, Any]) -> str:
    return str(settings["NEWAPI_BASE_URL"]).rstrip("/")


async def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.request(method, url, headers=headers, json=json_body)
        except httpx.HTTPError as exc:
            raise NewApiError(f"NewAPI request failed: {exc}") from exc

        if resp.status_code == 401:
            raise NewApiError("NewAPI authentication failed (401) — check tokens")
        if resp.status_code == 429:
            if attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "NewAPI 429 on %s %s (attempt %d/%d), retrying in %.1fs",
                    method, url.split("?")[0], attempt + 1, _MAX_RETRIES + 1, delay,
                )
                await asyncio.sleep(delay)
                continue
            raise NewApiError(f"NewAPI returned 429 after {_MAX_RETRIES + 1} attempts")
        if resp.status_code >= 400:
            body = resp.text[:300]
            raise NewApiError(f"NewAPI returned {resp.status_code}: {body}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise NewApiError(f"NewAPI returned non-JSON response: {resp.text[:200]}") from exc

        if not data.get("success", True):
            raise NewApiError(f"NewAPI error: {data.get('message', 'unknown')}")
        return data

    # Should not reach here, but just in case
    raise NewApiError("NewAPI request failed: max retries exceeded")


# ── Token CRUD (uses pool user's access token) ──


async def create_token(
    db: Any,
    *,
    name: str,
    remain_quota: int,
    model_limits: str | None = None,
    expired_time: int = -1,
) -> int:
    """Create a NewAPI token under the pool user and return its id.

    NewAPI's ``POST /api/token/`` returns only ``{"success":true}`` without
    the created token id, so a follow-up search by exact name is required
    to obtain it. Callers MUST use a unique ``name`` (e.g. with a random
    suffix) so the search result is unambiguous.
    """
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    body: dict[str, Any] = {
        "name": name,
        "remain_quota": remain_quota,
        "expired_time": expired_time,
        "unlimited_quota": False,
        "model_limits_enabled": bool(model_limits),
        "model_limits": model_limits or "",
        "allow_ips": "",
        "group": "default",
    }
    await _request(
        "POST",
        f"{_base_url(settings)}/api/token/",
        headers=_pool_user_headers(settings),
        json_body=body,
    )
    token_id = await find_token_by_name(db, name)
    if token_id is None:
        raise NewApiError(
            f"create_token succeeded but token '{name}' not found via search"
        )
    return token_id


async def find_token_by_name(db: Any, name: str) -> int | None:
    """Search for a token by exact name. Returns the token id or None.

    Raises ``NewApiError`` if multiple tokens share the same name — this
    indicates a caller bug (non-unique name) that must be fixed, not
    silently masked.
    """
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    data = await _request(
        "GET",
        f"{_base_url(settings)}/api/token/search?keyword={name}&p=1&page_size=10",
        headers=_pool_user_headers(settings),
    )
    items = data.get("data", {}).get("items", [])
    matches = [int(item["id"]) for item in items if item.get("name") == name]
    if not matches:
        return None
    if len(matches) > 1:
        raise NewApiError(
            f"multiple tokens found with name '{name}' (ids: {matches}) — "
            "token name must be unique"
        )
    return matches[0]


async def get_token_key(db: Any, token_id: int) -> str:
    """Fetch the plaintext API key for a token."""
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    data = await _request(
        "POST",
        f"{_base_url(settings)}/api/token/{token_id}/key",
        headers=_pool_user_headers(settings),
    )
    key = data.get("data", {}).get("key")
    if not key:
        raise NewApiError(f"NewAPI returned empty key for token {token_id}")
    return str(key)


async def update_token(
    db: Any,
    token_id: int,
    *,
    remain_quota: int | None = None,
    status: int | None = None,
    model_limits: str | None = None,
) -> dict[str, Any]:
    """Update a NewAPI token's quota / status / model limits."""
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    body: dict[str, Any] = {"id": token_id}
    if remain_quota is not None:
        body["remain_quota"] = remain_quota
    if status is not None:
        body["status"] = status
    if model_limits is not None:
        body["model_limits_enabled"] = bool(model_limits)
        body["model_limits"] = model_limits
    body["name"] = ""
    body["expired_time"] = -1
    body["unlimited_quota"] = False
    body["allow_ips"] = ""
    body["group"] = "default"
    return await _request(
        "PUT",
        f"{_base_url(settings)}/api/token/",
        headers=_pool_user_headers(settings),
        json_body=body,
    )


async def delete_token(db: Any, token_id: int) -> dict[str, Any]:
    """Delete a NewAPI token (revoke)."""
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    return await _request(
        "DELETE",
        f"{_base_url(settings)}/api/token/{token_id}",
        headers=_pool_user_headers(settings),
    )


# ── Usage query (uses the sk-xxx key itself, no admin token needed) ──


async def get_token_usage(api_key: str, base_url: str) -> dict[str, Any]:
    """Query token usage via Bearer sk-xxx. Returns raw usage data."""
    url = f"{base_url.rstrip('/')}/api/usage/token/"
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
    except httpx.HTTPError as exc:
        raise NewApiError(f"usage query failed: {exc}") from exc
    if resp.status_code >= 400:
        raise NewApiError(f"usage query returned {resp.status_code}")
    data = resp.json()
    return data.get("data", {})
