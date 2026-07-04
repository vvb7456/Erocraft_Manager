"""NewAPI management API client.

Wraps the NewAPI HTTP API for user / subscription / token CRUD and
usage queries. All requests use short-lived ``httpx.AsyncClient``
instances with ``trust_env=False``.

Architecture (post 20260703_llm_sub):
  * **Admin token** — used for user CRUD, subscription plan CRUD,
    subscription binding, group listing, and subscription queries.
  * **Per-server user access token** — used for token CRUD under that
    user (create / search / key / delete). Stored on ``ServerLlmKey``.
  * The old pool-user pattern is gone; each server gets its own NewAPI
    user with a native subscription.
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
    if not base_url or not admin_token:
        raise NewApiNotConfigured("NEWAPI_BASE_URL or NEWAPI_ADMIN_TOKEN not set")


def _base_url(settings: dict[str, Any]) -> str:
    return str(settings["NEWAPI_BASE_URL"]).rstrip("/")


def _admin_headers(settings: dict[str, Any]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings['NEWAPI_ADMIN_TOKEN']}",
        "New-Api-User": "1",
        "Content-Type": "application/json",
    }


def _user_headers(access_token: str, user_id: int) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "New-Api-User": str(user_id),
        "Content-Type": "application/json",
    }


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

    raise NewApiError("NewAPI request failed: max retries exceeded")


# ── User management (admin token) ──


async def create_user(db: Any, *, username: str, password: str) -> int:
    """Create a NewAPI user. Returns the new user id.

    NewAPI ``POST /api/user/`` returns only ``{"success":true}`` without
    the created user id, so a follow-up search by exact username is required.
    """
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    body: dict[str, Any] = {
        "username": username,
        "password": password,
        "display_name": username,
        "role": 1,
    }
    await _request(
        "POST",
        f"{_base_url(settings)}/api/user/",
        headers=_admin_headers(settings),
        json_body=body,
    )
    user_id = await search_user_id(db, username)
    if user_id is None:
        raise NewApiError(
            f"create_user succeeded but user '{username}' not found via search"
        )
    return user_id


async def search_user_id(db: Any, username: str) -> int | None:
    """Search for a user by exact username. Returns the user id or None."""
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    import urllib.parse

    encoded = urllib.parse.quote(username)
    data = await _request(
        "GET",
        f"{_base_url(settings)}/api/user/search?keyword={encoded}&page=1&size=10",
        headers=_admin_headers(settings),
    )
    items = data.get("data", {}).get("items", [])
    matches = [
        int(item["id"])
        for item in items
        if item.get("username") == username and not item.get("DeletedAt")
    ]
    if not matches:
        return None
    if len(matches) > 1:
        raise NewApiError(
            f"multiple users found with username '{username}' (ids: {matches})"
        )
    return matches[0]


async def delete_user(db: Any, user_id: int) -> dict[str, Any]:
    """Hard-delete a NewAPI user (cascades to tokens + subscriptions).

    Uses ``DELETE /api/user/:id`` which calls ``HardDeleteUserById``
    (GORM ``Unscoped().Delete``). This permanently removes the user row
    and frees the username for future re-provisioning.

    Note: NewAPI's ``POST /api/user/manage {action:"delete"}`` does a
    GORM soft-delete (sets ``deleted_at``), which leaves the username
    unique constraint in place and blocks re-creation. We must use the
    hard-delete endpoint instead.
    """
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    return await _request(
        "DELETE",
        f"{_base_url(settings)}/api/user/{user_id}",
        headers=_admin_headers(settings),
    )


async def get_user(db: Any, user_id: int) -> dict[str, Any]:
    """Get NewAPI user details."""
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    return await _request(
        "GET",
        f"{_base_url(settings)}/api/user/{user_id}",
        headers=_admin_headers(settings),
    )


async def login_and_gen_access_token(
    db: Any, *, username: str, password: str
) -> str:
    """Login as a user and generate their access token.

    NewAPI login uses session cookies; we then call ``GET /api/user/token``
    to get the access token (char 32). Both calls use the session cookie
    from login.
    """
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    base = _base_url(settings)
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, trust_env=False) as client:
            login_resp = await client.post(
                f"{base}/api/user/login",
                json={"username": username, "password": password},
            )
            if login_resp.status_code >= 400:
                raise NewApiError(
                    f"NewAPI login failed ({login_resp.status_code}): "
                    f"{login_resp.text[:200]}"
                )
            login_data = login_resp.json()
            if not login_data.get("success", False):
                raise NewApiError(
                    f"NewAPI login failed: {login_data.get('message', 'unknown')}"
                )
            cookies = login_resp.cookies
            login_user_id = login_data.get("data", {}).get("id")
            if not login_user_id:
                raise NewApiError("NewAPI login response missing user id")

            token_resp = await client.get(
                f"{base}/api/user/token",
                cookies=cookies,
                headers={"New-Api-User": str(login_user_id)},
            )
            if token_resp.status_code >= 400:
                raise NewApiError(
                    f"NewAPI gen token failed ({token_resp.status_code}): "
                    f"{token_resp.text[:200]}"
                )
            token_data = token_resp.json()
            if not token_data.get("success", False):
                raise NewApiError(
                    f"NewAPI gen token failed: "
                    f"{token_data.get('message', 'unknown')}"
                )
            access_token = token_data.get("data")
            if not access_token:
                raise NewApiError("NewAPI returned empty access token")
            return str(access_token)
    except httpx.HTTPError as exc:
        raise NewApiError(f"NewAPI login/gen-token HTTP error: {exc}") from exc


async def set_billing_preference(
    db: Any, *, access_token: str, user_id: int, preference: str = "subscription_only"
) -> dict[str, Any]:
    """Set the user's billing preference (e.g. subscription_only).

    Uses the user's own access token + ``New-Api-User`` header (UserAuth).
    Route: ``PUT /api/subscription/self/preference``.
    """
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    return await _request(
        "PUT",
        f"{_base_url(settings)}/api/subscription/self/preference",
        headers=_user_headers(access_token, user_id),
        json_body={"billing_preference": preference},
    )


# ── Subscription plan management (admin token) ──


async def create_plan(
    db: Any,
    *,
    title: str,
    total_amount: int,
    upgrade_group: str,
    duration_unit: str = "year",
    duration_value: int = 100,
    quota_reset_period: str = "custom",
    quota_reset_custom_seconds: int = 2592000,
    price_amount: float = 0,
    enabled: bool = True,
    allow_wallet_overflow: bool = False,
    allow_balance_pay: bool = False,
    max_purchase_per_user: int = 0,
    sort_order: int = 0,
) -> int:
    """Create a NewAPI SubscriptionPlan. Returns the new plan id.

    Body uses the ``{plan: {...}}`` wrapper required by
    ``AdminUpsertSubscriptionPlanRequest``.
    """
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    body = {
        "plan": {
            "title": title,
            "subtitle": "",
            "price_amount": price_amount,
            "currency": "USD",
            "duration_unit": duration_unit,
            "duration_value": duration_value,
            "enabled": enabled,
            "sort_order": sort_order,
            "allow_balance_pay": allow_balance_pay,
            "allow_wallet_overflow": allow_wallet_overflow,
            "max_purchase_per_user": max_purchase_per_user,
            "total_amount": total_amount,
            "upgrade_group": upgrade_group,
            "downgrade_group": "",
            "quota_reset_period": quota_reset_period,
            "quota_reset_custom_seconds": quota_reset_custom_seconds,
        }
    }
    data = await _request(
        "POST",
        f"{_base_url(settings)}/api/subscription/admin/plans",
        headers=_admin_headers(settings),
        json_body=body,
    )
    plan_id = data.get("data", {}).get("id") if isinstance(data.get("data"), dict) else data.get("data")
    if not plan_id:
        raise NewApiError("create_plan succeeded but no plan id in response")
    return int(plan_id)


async def update_plan(
    db: Any,
    plan_id: int,
    *,
    title: str,
    total_amount: int,
    upgrade_group: str,
    duration_unit: str = "year",
    duration_value: int = 100,
    quota_reset_period: str = "custom",
    quota_reset_custom_seconds: int = 2592000,
    price_amount: float = 0,
    enabled: bool = True,
    allow_wallet_overflow: bool = False,
    allow_balance_pay: bool = False,
    max_purchase_per_user: int = 0,
    sort_order: int = 0,
) -> dict[str, Any]:
    """Update a NewAPI SubscriptionPlan.

    NewAPI's PUT does a full replacement — all fields in the updateMap
    are written from the request body, with Go zero values for omitted
    fields. So we must always send every field, not just changed ones.
    """
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    plan_body: dict[str, Any] = {
        "title": title,
        "subtitle": "",
        "price_amount": price_amount,
        "currency": "USD",
        "duration_unit": duration_unit,
        "duration_value": duration_value,
        "enabled": enabled,
        "sort_order": sort_order,
        "max_purchase_per_user": max_purchase_per_user,
        "total_amount": total_amount,
        "upgrade_group": upgrade_group,
        "downgrade_group": "",
        "quota_reset_period": quota_reset_period,
        "quota_reset_custom_seconds": quota_reset_custom_seconds,
    }
    return await _request(
        "PUT",
        f"{_base_url(settings)}/api/subscription/admin/plans/{plan_id}",
        headers=_admin_headers(settings),
        json_body={"plan": plan_body},
    )


async def list_plans(db: Any) -> list[dict[str, Any]]:
    """List all NewAPI subscription plans."""
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    data = await _request(
        "GET",
        f"{_base_url(settings)}/api/subscription/admin/plans",
        headers=_admin_headers(settings),
    )
    plans = data.get("data", [])
    return plans if isinstance(plans, list) else []


async def set_plan_status(
    db: Any, plan_id: int, *, enabled: bool
) -> dict[str, Any]:
    """Enable / disable a subscription plan (PATCH)."""
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    return await _request(
        "PATCH",
        f"{_base_url(settings)}/api/subscription/admin/plans/{plan_id}",
        headers=_admin_headers(settings),
        json_body={"enabled": enabled},
    )


# ── User subscription management (admin token) ──


async def bind_subscription(
    db: Any, *, user_id: int, plan_id: int
) -> None:
    """Bind a subscription plan to a user (admin, no payment).

    Route: ``POST /api/subscription/admin/users/:id/subscriptions``.
    NewAPI does not return the subscription id, so callers needing it
    must follow up with ``get_user_subscriptions``.
    """
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    await _request(
        "POST",
        f"{_base_url(settings)}/api/subscription/admin/users/{user_id}/subscriptions",
        headers=_admin_headers(settings),
        json_body={"plan_id": plan_id},
    )


async def get_user_subscriptions(
    db: Any, user_id: int
) -> list[dict[str, Any]]:
    """Get all subscriptions for a user.

    Returns the raw ``SubscriptionSummary`` list, each containing a
    ``subscription`` object with ``amount_total``, ``amount_used``,
    ``next_reset_time``, ``status``, ``end_time``, etc.
    """
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    data = await _request(
        "GET",
        f"{_base_url(settings)}/api/subscription/admin/users/{user_id}/subscriptions",
        headers=_admin_headers(settings),
    )
    items = data.get("data", [])
    return items if isinstance(items, list) else []


async def get_active_subscription_id(
    db: Any, user_id: int
) -> int | None:
    """Get the id of the user's active subscription, or None.

    Used after ``bind_subscription`` to retrieve the newly created
    subscription id (NewAPI doesn't return it from bind).
    """
    subs = await get_user_subscriptions(db, user_id)
    for item in subs:
        sub = item.get("subscription", {}) if isinstance(item, dict) else {}
        if sub.get("status") == "active":
            sid = sub.get("id")
            if sid:
                return int(sid)
    return None


async def invalidate_subscription(
    db: Any, subscription_id: int
) -> dict[str, Any]:
    """Invalidate (cancel) a user subscription.

    Sets status to ``cancelled`` and end_time to now. Triggers group
    downgrade logic.
    """
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    return await _request(
        "POST",
        f"{_base_url(settings)}/api/subscription/admin/user_subscriptions/{subscription_id}/invalidate",
        headers=_admin_headers(settings),
    )


async def delete_subscription(
    db: Any, subscription_id: int
) -> dict[str, Any]:
    """Hard-delete a user subscription record."""
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    return await _request(
        "DELETE",
        f"{_base_url(settings)}/api/subscription/admin/user_subscriptions/{subscription_id}",
        headers=_admin_headers(settings),
    )


async def reset_subscription_usage(
    db: Any, *, user_id: int, plan_id: int, old_subscription_id: int
) -> int:
    """Reset a user's subscription usage by invalidating + rebinding.

    NewAPI has no direct API to zero ``AmountUsed``, so we invalidate
    the old subscription and bind a new one. Returns the new subscription id.
    """
    await invalidate_subscription(db, old_subscription_id)
    await bind_subscription(db, user_id=user_id, plan_id=plan_id)
    new_sub_id = await get_active_subscription_id(db, user_id)
    if new_sub_id is None:
        raise NewApiError(
            f"reset_subscription: no active subscription found after rebind "
            f"(user_id={user_id}, plan_id={plan_id})"
        )
    return new_sub_id


# ── Group listing (admin token) ──


async def list_groups(db: Any) -> list[str]:
    """List all NewAPI group names (method 3A: group → model access).

    Route: ``GET /api/group/`` (AdminAuth). Returns group names from
    the group ratio setting, e.g. ``["default", "vip", "svip"]``.
    """
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    data = await _request(
        "GET",
        f"{_base_url(settings)}/api/group/",
        headers=_admin_headers(settings),
    )
    groups = data.get("data", [])
    return [str(g) for g in groups] if isinstance(groups, list) else []


# ── Token CRUD (uses the per-server user's access token) ──


async def create_token(
    db: Any,
    *,
    access_token: str,
    user_id: int,
    name: str,
    group: str = "",
    unlimited_quota: bool = True,
) -> int:
    """Create a NewAPI token under the per-server user and return its id.

    Uses the user's own access token + ``New-Api-User`` header (required
    by NewAPI — admin token cannot create tokens for other users).

    NewAPI's ``POST /api/token/`` returns only ``{"success":true}`` without
    the created token id, so a follow-up search by exact name is required.
    """
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    body: dict[str, Any] = {
        "name": name,
        "remain_quota": 0,
        "expired_time": -1,
        "unlimited_quota": unlimited_quota,
        "model_limits_enabled": False,
        "model_limits": "",
        "allow_ips": "",
        "group": group,
    }
    await _request(
        "POST",
        f"{_base_url(settings)}/api/token/",
        headers=_user_headers(access_token, user_id),
        json_body=body,
    )
    token_id = await find_token_by_name(
        db, access_token=access_token, user_id=user_id, name=name
    )
    if token_id is None:
        raise NewApiError(
            f"create_token succeeded but token '{name}' not found via search"
        )
    return token_id


async def find_token_by_name(
    db: Any, *, access_token: str, user_id: int, name: str
) -> int | None:
    """Search for a token by exact name. Returns the token id or None.

    Raises ``NewApiError`` if multiple tokens share the same name.
    """
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    data = await _request(
        "GET",
        f"{_base_url(settings)}/api/token/search?keyword={name}&p=1&page_size=10",
        headers=_user_headers(access_token, user_id),
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


async def get_token_key(
    db: Any, *, access_token: str, user_id: int, token_id: int
) -> str:
    """Fetch the plaintext API key for a token."""
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    data = await _request(
        "POST",
        f"{_base_url(settings)}/api/token/{token_id}/key",
        headers=_user_headers(access_token, user_id),
    )
    key = data.get("data", {}).get("key")
    if not key:
        raise NewApiError(f"NewAPI returned empty key for token {token_id}")
    return str(key)


async def update_token(
    db: Any,
    *,
    access_token: str,
    user_id: int,
    token_id: int,
    status: int | None = None,
) -> dict[str, Any]:
    """Update a NewAPI token's status (1=active, 2=disabled).

    Uses the ``?status_only=1`` query param so only ``status`` is written
    — other fields (name, remain_quota, etc.) are left untouched.
    """
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    body: dict[str, Any] = {"id": token_id}
    if status is not None:
        body["status"] = status
    return await _request(
        "PUT",
        f"{_base_url(settings)}/api/token/?status_only=1",
        headers=_user_headers(access_token, user_id),
        json_body=body,
    )


async def delete_token(
    db: Any, *, access_token: str, user_id: int, token_id: int
) -> dict[str, Any]:
    """Delete a NewAPI token."""
    settings = await _read_llm_settings(db)
    _check_configured(settings)
    return await _request(
        "DELETE",
        f"{_base_url(settings)}/api/token/{token_id}",
        headers=_user_headers(access_token, user_id),
    )
