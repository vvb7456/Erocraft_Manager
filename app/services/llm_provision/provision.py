"""Provision / revoke / upgrade LLM keys for servers.

Orchestrates NewAPI token creation, key retrieval, and local DB record
management. Called from ``apply_engine._run_post_actions`` and
``server_lifecycle.delete_server``.

Config injection into SillyTavern is handled entirely by the egg —
Manager only creates the NewAPI token and stores the key locally. The
egg's install script / config_files mechanism is responsible for
materializing the API key / endpoint / model into the container.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime_settings import LLM_SPECS, defaults_for
from app.core.settings_store import get_settings_store
from app.core.time import utc_naive_now
from app.db.models.manager import ServerLlmKey
from app.db.models.pterodactyl import PteroServer
from app.services.audit import log_manager_activity
from app.services.llm_provision import newapi_client

logger = logging.getLogger(__name__)


def _llm_enabled_in_snapshot(snapshot: dict[str, Any]) -> bool:
    return bool(snapshot.get("llm_enabled")) and int(snapshot.get("llm_quota_grant", 0)) > 0


async def _is_llm_globally_enabled(db: AsyncSession) -> bool:
    store = get_settings_store()
    values = await store.get_many(db, defaults_for(LLM_SPECS))
    return bool(values.get("LLM_ENABLED"))


async def provision_for_server(
    db: AsyncSession,
    server_id: int,
    user_id: int,
    snapshot: dict[str, Any],
) -> ServerLlmKey | None:
    """Provision a NewAPI token for a server after order apply.

    Returns the created/updated ``ServerLlmKey`` row, or ``None`` if LLM is
    not enabled for this plan or globally. Idempotent — if a key row already
    exists for this server, updates it instead of creating a duplicate.
    """
    if not await _is_llm_globally_enabled(db):
        return None
    if not _llm_enabled_in_snapshot(snapshot):
        return None

    quota_grant = int(snapshot["llm_quota_grant"])
    model_limits = snapshot.get("llm_model_limits") or None

    existing = await db.get(ServerLlmKey, server_id)
    if existing is not None:
        existing.quota_grant = quota_grant
        existing.model_limits = model_limits
        existing.status = "active"
        await db.flush()
        await log_manager_activity(
            db,
            actor="system",
            category="billing",
            status="success",
            detail_key="llm.provision",
            detail_params={
                "server_id": server_id,
                "plan_code": "",
                "quota_grant": quota_grant,
                "token_id": existing.newapi_token_id,
            },
        )
        logger.info("updated LLM key for server %s (active)", server_id)
        return existing

    token_name = f"srv_{server_id}"
    await newapi_client.create_token(
        db,
        name=token_name,
        remain_quota=quota_grant,
        model_limits=model_limits,
    )
    token_id = await newapi_client.find_token_by_name(db, token_name)
    if not token_id:
        raise newapi_client.NewApiError(
            f"create_token succeeded but token '{token_name}' not found"
        )

    api_key = await newapi_client.get_token_key(db, token_id)

    now = utc_naive_now()
    row = ServerLlmKey(
        server_id=server_id,
        user_id=user_id,
        newapi_token_id=token_id,
        api_key=f"sk-{api_key}",
        quota_grant=quota_grant,
        quota_used=0,
        quota_available=quota_grant,
        model_limits=model_limits,
        status="active",
        last_reset_at=now,
        reset_day=min(now.day, 28),
    )
    db.add(row)
    await db.flush()
    await log_manager_activity(
        db,
        actor="system",
        category="billing",
        status="success",
        detail_key="llm.provision",
        detail_params={
            "server_id": server_id,
            "plan_code": "",
            "quota_grant": quota_grant,
            "token_id": token_id,
        },
    )
    logger.info(
        "provisioned LLM key for server %s: token_id=%s quota=%d",
        server_id, token_id, quota_grant,
    )
    return row


async def revoke_for_server(db: AsyncSession, server_id: int) -> None:
    """Revoke the NewAPI token and remove the local key row.

    Best-effort: if NewAPI is unreachable, the local row is still deleted
    (the token can be manually cleaned up from the NewAPI UI later).
    """
    row = await db.get(ServerLlmKey, server_id)
    if row is None:
        return

    try:
        await newapi_client.delete_token(db, row.newapi_token_id)
    except Exception:
        logger.warning(
            "failed to delete NewAPI token %s for server %s, "
            "removing local row anyway",
            row.newapi_token_id, server_id,
            exc_info=True,
        )

    await db.delete(row)
    await db.flush()
    await log_manager_activity(
        db,
        actor="system",
        category="billing",
        status="info",
        detail_key="llm.revoke",
        detail_params={
            "server_id": server_id,
            "token_id": row.newapi_token_id,
        },
    )
    logger.info("revoked LLM key for server %s", server_id)


class LlmAdminError(Exception):
    """Raised for admin LLM management operations (no key, NewAPI failure, etc.)."""


async def admin_update_key(
    db: AsyncSession,
    server_id: int,
    *,
    quota_grant: int | None = None,
    model_limits: str | None = None,
    actor: str = "admin",
) -> ServerLlmKey:
    """Adjust an existing key's quota grant and/or allowed models.

    Syncs to NewAPI (remain_quota is set to the new grant; usage is NOT reset
    here — use ``admin_reset_usage`` for that). Raises ``LlmAdminError`` if no
    key row exists or the NewAPI call fails.
    """
    row = await db.get(ServerLlmKey, server_id)
    if row is None:
        raise LlmAdminError("no LLM key for this server")

    new_grant = int(quota_grant) if quota_grant is not None else row.quota_grant
    # model_limits: None sentinel means "unchanged"; empty string means "all models"
    new_models = row.model_limits if model_limits is None else (model_limits or None)

    try:
        await newapi_client.update_token(
            db,
            row.newapi_token_id,
            remain_quota=new_grant,
            model_limits=new_models or "",
        )
    except Exception as exc:  # noqa: BLE001
        raise LlmAdminError(f"NewAPI update failed: {exc}") from exc

    row.quota_grant = new_grant
    row.model_limits = new_models
    await db.flush()
    await log_manager_activity(
        db,
        actor=actor,
        category="server",
        status="success",
        detail_key="llm.admin.update",
        detail_params={
            "server_id": server_id,
            "quota_grant": new_grant,
            "models": new_models or "",
        },
    )
    logger.info("admin updated LLM key for server %s: quota=%d models=%s", server_id, new_grant, new_models)
    return row


async def admin_reset_key(db: AsyncSession, server_id: int, *, actor: str = "admin") -> ServerLlmKey:
    """Revoke the old NewAPI token and mint a fresh one (new ``sk-xxx``).

    Preserves the local row's quota_grant / model_limits / reset schedule.
    Raises ``LlmAdminError`` if no key row exists or NewAPI fails.
    """
    row = await db.get(ServerLlmKey, server_id)
    if row is None:
        raise LlmAdminError("no LLM key for this server")

    old_token_id = row.newapi_token_id

    # Best-effort delete of the old token; proceed even if it fails.
    try:
        await newapi_client.delete_token(db, old_token_id)
    except Exception:  # noqa: BLE001
        logger.warning("reset: failed to delete old token %s for server %s", old_token_id, server_id, exc_info=True)

    token_name = f"srv_{server_id}"
    try:
        await newapi_client.create_token(
            db,
            name=token_name,
            remain_quota=row.quota_grant,
            model_limits=row.model_limits,
        )
        new_token_id = await newapi_client.find_token_by_name(db, token_name)
        if not new_token_id:
            raise LlmAdminError(f"create_token succeeded but token '{token_name}' not found")
        api_key = await newapi_client.get_token_key(db, new_token_id)
    except LlmAdminError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LlmAdminError(f"NewAPI create failed: {exc}") from exc

    row.newapi_token_id = new_token_id
    row.api_key = f"sk-{api_key}"
    if row.status == "revoked":
        row.status = "active"
    await db.flush()
    await log_manager_activity(
        db,
        actor=actor,
        category="server",
        status="success",
        detail_key="llm.admin.reset",
        detail_params={"server_id": server_id, "old_token_id": old_token_id, "token_id": new_token_id},
    )
    logger.info("admin reset LLM key for server %s: %s -> %s", server_id, old_token_id, new_token_id)
    return row


async def admin_set_status(
    db: AsyncSession,
    server_id: int,
    *,
    enabled: bool,
    actor: str = "admin",
) -> ServerLlmKey:
    """Enable / disable a key via NewAPI token status (1=active, 2=disabled).

    Local status toggles between ``active`` and ``disabled``.
    Raises ``LlmAdminError`` if no key row exists or NewAPI fails.
    """
    row = await db.get(ServerLlmKey, server_id)
    if row is None:
        raise LlmAdminError("no LLM key for this server")

    newapi_status = 1 if enabled else 2
    try:
        await newapi_client.update_token(db, row.newapi_token_id, status=newapi_status)
    except Exception as exc:  # noqa: BLE001
        raise LlmAdminError(f"NewAPI status update failed: {exc}") from exc

    row.status = "active" if enabled else "disabled"
    await db.flush()
    await log_manager_activity(
        db,
        actor=actor,
        category="server",
        status="success",
        detail_key="llm.admin.status",
        detail_params={"server_id": server_id, "enabled": str(enabled).lower()},
    )
    logger.info("admin set LLM key status for server %s: enabled=%s", server_id, enabled)
    return row


async def admin_reset_usage(db: AsyncSession, server_id: int, *, actor: str = "admin") -> ServerLlmKey:
    """Manually refill this month's quota: reset NewAPI remain_quota to grant.

    Clears cached usage counters and refreshes ``last_reset_at``.
    Raises ``LlmAdminError`` if no key row exists or NewAPI fails.
    """
    row = await db.get(ServerLlmKey, server_id)
    if row is None:
        raise LlmAdminError("no LLM key for this server")

    try:
        await newapi_client.update_token(db, row.newapi_token_id, remain_quota=row.quota_grant)
    except Exception as exc:  # noqa: BLE001
        raise LlmAdminError(f"NewAPI quota reset failed: {exc}") from exc

    row.quota_available = row.quota_grant
    row.quota_used = 0
    row.last_reset_at = utc_naive_now()
    if row.status == "exhausted":
        row.status = "active"
    await db.flush()
    await log_manager_activity(
        db,
        actor=actor,
        category="server",
        status="success",
        detail_key="llm.admin.reset_usage",
        detail_params={"server_id": server_id, "quota_grant": row.quota_grant},
    )
    logger.info("admin reset usage for server %s: quota=%d", server_id, row.quota_grant)
    return row


async def admin_revoke(db: AsyncSession, server_id: int, *, actor: str = "admin") -> None:
    """Admin revoke: delete NewAPI token + local row (wraps revoke_for_server)."""
    row = await db.get(ServerLlmKey, server_id)
    if row is None:
        raise LlmAdminError("no LLM key for this server")
    token_id = row.newapi_token_id
    try:
        await newapi_client.delete_token(db, token_id)
    except Exception:  # noqa: BLE001
        logger.warning("admin revoke: failed to delete token %s for server %s", token_id, server_id, exc_info=True)
    await db.delete(row)
    await db.flush()
    await log_manager_activity(
        db,
        actor=actor,
        category="server",
        status="info",
        detail_key="llm.admin.revoke",
        detail_params={"server_id": server_id, "token_id": token_id},
    )
    logger.info("admin revoked LLM key for server %s", server_id)


async def update_for_upgrade(
    db: AsyncSession,
    server_id: int,
    new_snapshot: dict[str, Any],
) -> None:
    """Update an existing key's quota/model limits after an upgrade/convert."""
    if not _llm_enabled_in_snapshot(new_snapshot):
        await revoke_for_server(db, server_id)
        return

    row = await db.get(ServerLlmKey, server_id)
    if row is None:
        user_id = 0
        server = await db.get(PteroServer, server_id)
        if server is not None:
            user_id = server.owner_id
        await provision_for_server(db, server_id, user_id, new_snapshot)
        return

    new_grant = int(new_snapshot["llm_quota_grant"])
    new_models = new_snapshot.get("llm_model_limits") or None

    try:
        await newapi_client.update_token(
            db,
            row.newapi_token_id,
            remain_quota=new_grant,
            model_limits=new_models,
        )
    except Exception:
        logger.warning(
            "failed to update NewAPI token %s for server %s",
            row.newapi_token_id, server_id,
            exc_info=True,
        )
        return

    row.quota_grant = new_grant
    row.quota_available = new_grant
    row.quota_used = 0
    row.model_limits = new_models
    row.last_reset_at = utc_naive_now()
    if row.status == "exhausted":
        row.status = "active"
    await db.flush()
    await log_manager_activity(
        db,
        actor="system",
        category="billing",
        status="success",
        detail_key="llm.upgrade",
        detail_params={
            "server_id": server_id,
            "quota_grant": new_grant,
            "models": new_models or "",
        },
    )
    logger.info(
        "updated LLM key for server %s: quota=%d models=%s",
        server_id, new_grant, new_models,
    )
