"""Provision / revoke / upgrade LLM subscriptions for servers.

Orchestrates NewAPI per-server user creation, subscription binding,
and token CRUD. Called from ``apply_engine._run_post_actions`` and
``server_lifecycle.delete_server``.

Each LLM-enabled server gets its own NewAPI user (``srv_{server_id}``)
with a native subscription tied to the plan's NewAPI SubscriptionPlan.
The token (sk-xxx) is set to ``unlimited_quota`` — quota enforcement
is entirely via the subscription (``subscription_only`` billing preference).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
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

_USER_PASSWORD_LEN = 16


def _gen_password() -> str:
    return secrets.token_urlsafe(_USER_PASSWORD_LEN)[:20]


def _llm_enabled_in_snapshot(snapshot: dict[str, Any]) -> bool:
    return bool(snapshot.get("llm_enabled")) and int(snapshot.get("llm_quota_grant", 0)) > 0


async def _is_llm_globally_enabled(db: AsyncSession) -> bool:
    store = get_settings_store()
    values = await store.get_many(db, defaults_for(LLM_SPECS))
    return bool(values.get("LLM_ENABLED"))


async def _reprovision_existing(
    db: AsyncSession, row: ServerLlmKey, newapi_plan_id: int
) -> ServerLlmKey:
    uid = row.newapi_user_id
    access_token = row.newapi_user_access_token

    if row.newapi_subscription_id:
        try:
            await newapi_client.invalidate_subscription(
                db, row.newapi_subscription_id
            )
        except Exception:
            logger.warning(
                "reprovision server %s: failed to invalidate old sub %s",
                row.server_id, row.newapi_subscription_id, exc_info=True,
            )

    await newapi_client.bind_subscription(db, user_id=uid, plan_id=newapi_plan_id)
    new_sub_id = await newapi_client.get_active_subscription_id(db, uid)
    if new_sub_id is None:
        raise newapi_client.NewApiError(
            f"reprovision: no active subscription after rebind (user_id={uid})"
        )

    try:
        await newapi_client.update_token(
            db,
            access_token=access_token,
            user_id=uid,
            token_id=row.newapi_token_id,
            status=1,
        )
    except Exception:
        logger.warning(
            "reprovision server %s: failed to re-enable token %s",
            row.server_id, row.newapi_token_id, exc_info=True,
        )

    row.newapi_subscription_id = new_sub_id
    row.newapi_plan_id = newapi_plan_id
    row.status = "active"
    row.last_synced_at = utc_naive_now()
    await db.flush()

    await log_manager_activity(
        db,
        actor="system",
        category="billing",
        status="success",
        detail_key="llm.provision",
        detail_params={
            "server_id": row.server_id,
            "newapi_user_id": uid,
            "subscription_id": new_sub_id,
            "token_id": row.newapi_token_id,
        },
    )
    logger.info(
        "reprovisioned LLM for server %s: user=%s sub=%s",
        row.server_id, uid, new_sub_id,
    )
    return row


async def provision_for_server(
    db: AsyncSession,
    server_id: int,
    user_id: int,
    snapshot: dict[str, Any],
) -> ServerLlmKey | None:
    """Provision a NewAPI user + subscription + token for a server.

    Returns the created/updated ``ServerLlmKey`` row, or ``None`` if LLM
    is not enabled for this plan or globally. Idempotent — if a key row
    already exists for this server, updates it instead of creating a duplicate.
    """
    if not await _is_llm_globally_enabled(db):
        return None
    if not _llm_enabled_in_snapshot(snapshot):
        return None

    newapi_plan_id = int(snapshot.get("newapi_plan_id") or 0)
    if newapi_plan_id <= 0:
        logger.warning(
            "provision server %s: llm_enabled but newapi_plan_id missing in snapshot",
            server_id,
        )
        return None

    existing = await db.get(ServerLlmKey, server_id)
    if existing is not None and existing.status == "active":
        logger.info("LLM key already active for server %s, skipping", server_id)
        return existing

    if existing is not None and existing.newapi_user_id:
        return await _reprovision_existing(db, existing, newapi_plan_id)

    username = f"srv_{server_id}"
    password = _gen_password()

    # Step 1: create NewAPI user
    newapi_user_id = await newapi_client.create_user(
        db, username=username, password=password
    )

    try:
        # Step 2: login + generate access token
        access_token = await newapi_client.login_and_gen_access_token(
            db, username=username, password=password
        )

        # Steps 3-4 (subscription) and Steps 5-6 (token) are independent
        # — run them concurrently to halve the RTT wait.
        # NOTE: both chains call newapi_client functions that read
        # _read_llm_settings(db); this is safe because create_user +
        # login above have already warmed the settings cache, so no
        # DB access happens inside the gather.
        async def _subscription_chain() -> int:
            await newapi_client.bind_subscription(
                db, user_id=newapi_user_id, plan_id=newapi_plan_id
            )
            sub_id = await newapi_client.get_active_subscription_id(
                db, newapi_user_id
            )
            if sub_id is None:
                raise newapi_client.NewApiError(
                    f"no active subscription found after bind (user_id={newapi_user_id})"
                )
            await newapi_client.set_billing_preference(
                db,
                access_token=access_token,
                user_id=newapi_user_id,
                preference="subscription_only",
            )
            return sub_id

        async def _token_chain() -> tuple[int, str]:
            token_name = f"srv_{server_id}"
            token_id = await newapi_client.create_token(
                db,
                access_token=access_token,
                user_id=newapi_user_id,
                name=token_name,
                group="",
                unlimited_quota=True,
            )
            api_key_raw = await newapi_client.get_token_key(
                db, access_token=access_token, user_id=newapi_user_id, token_id=token_id
            )
            return token_id, api_key_raw

        sub_result, token_result = await asyncio.gather(
            _subscription_chain(), _token_chain(), return_exceptions=True
        )
        if isinstance(sub_result, Exception) or isinstance(token_result, Exception):
            raise sub_result if isinstance(sub_result, Exception) else token_result
        subscription_id = sub_result
        token_id, api_key_raw = token_result
    except Exception:
        # Rollback: delete the user (cascades to tokens + subscriptions)
        logger.warning(
            "provision failed for server %s, cleaning up NewAPI user %s",
            server_id, newapi_user_id, exc_info=True,
        )
        try:
            await newapi_client.delete_user(db, newapi_user_id)
        except Exception:
            logger.error(
                "cleanup failed: could not delete NewAPI user %s for server %s",
                newapi_user_id, server_id, exc_info=True,
            )
        raise

    # Step 6: persist locally
    if existing is not None:
        existing.newapi_user_id = newapi_user_id
        existing.newapi_user_access_token = access_token
        existing.newapi_user_password = password
        existing.newapi_subscription_id = subscription_id
        existing.newapi_plan_id = newapi_plan_id
        existing.newapi_token_id = token_id
        existing.api_key = f"sk-{api_key_raw}"
        existing.status = "active"
        existing.last_synced_at = utc_naive_now()
    else:
        existing = ServerLlmKey(
            server_id=server_id,
            user_id=user_id,
            newapi_user_id=newapi_user_id,
            newapi_user_access_token=access_token,
            newapi_user_password=password,
            newapi_subscription_id=subscription_id,
            newapi_plan_id=newapi_plan_id,
            newapi_token_id=token_id,
            api_key=f"sk-{api_key_raw}",
            status="active",
            last_synced_at=utc_naive_now(),
        )
        db.add(existing)
    await db.flush()

    await log_manager_activity(
        db,
        actor="system",
        category="billing",
        status="success",
        detail_key="llm.provision",
        detail_params={
            "server_id": server_id,
            "newapi_user_id": newapi_user_id,
            "subscription_id": subscription_id,
            "token_id": token_id,
        },
    )
    logger.info(
        "provisioned LLM for server %s: user=%s sub=%s token=%s",
        server_id, newapi_user_id, subscription_id, token_id,
    )
    return existing


async def revoke_for_server(db: AsyncSession, server_id: int) -> None:
    """Revoke: delete the NewAPI user (cascades to tokens + subscriptions)
    and remove the local key row.

    Best-effort: if NewAPI is unreachable, the local row is still deleted.
    """
    row = await db.get(ServerLlmKey, server_id)
    if row is None:
        return

    try:
        await newapi_client.delete_user(db, row.newapi_user_id)
    except Exception:
        logger.warning(
            "failed to delete NewAPI user %s for server %s, "
            "removing local row anyway",
            row.newapi_user_id, server_id,
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
            "newapi_user_id": row.newapi_user_id,
        },
    )
    logger.info("revoked LLM for server %s", server_id)


class LlmAdminError(Exception):
    """Raised for admin LLM management operations (no key, NewAPI failure, etc.)."""


async def admin_set_status(
    db: AsyncSession,
    server_id: int,
    *,
    enabled: bool,
    actor: str = "admin",
) -> ServerLlmKey:
    """Enable / disable a key via NewAPI token status (1=active, 2=disabled).

    Local status toggles between ``active`` and ``disabled``.
    """
    row = await db.get(ServerLlmKey, server_id)
    if row is None:
        raise LlmAdminError("no LLM key for this server")

    newapi_status = 1 if enabled else 2
    try:
        await newapi_client.update_token(
            db,
            access_token=row.newapi_user_access_token,
            user_id=row.newapi_user_id,
            token_id=row.newapi_token_id,
            status=newapi_status,
        )
    except Exception as exc:
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
    logger.info("admin set LLM status for server %s: enabled=%s", server_id, enabled)
    return row


async def admin_reset_usage(
    db: AsyncSession, server_id: int, *, actor: str = "admin"
) -> ServerLlmKey:
    """Reset the server's subscription usage by invalidating + rebinding.

    NewAPI has no direct API to zero ``AmountUsed``, so we invalidate the
    old subscription and bind a new one from the same plan.
    """
    row = await db.get(ServerLlmKey, server_id)
    if row is None:
        raise LlmAdminError("no LLM key for this server")

    plan_id = row.newapi_plan_id
    if plan_id is None or plan_id <= 0:
        raise LlmAdminError("no newapi_plan_id on this key row")

    try:
        new_sub_id = await newapi_client.reset_subscription_usage(
            db,
            user_id=row.newapi_user_id,
            plan_id=int(plan_id),
            old_subscription_id=row.newapi_subscription_id,
        )
    except Exception as exc:
        raise LlmAdminError(f"NewAPI reset usage failed: {exc}") from exc

    old_sub_id = row.newapi_subscription_id
    row.newapi_subscription_id = new_sub_id
    row.last_synced_at = utc_naive_now()
    if row.status == "disabled":
        pass  # keep disabled
    else:
        row.status = "active"
    await db.flush()
    await log_manager_activity(
        db,
        actor=actor,
        category="server",
        status="success",
        detail_key="llm.admin.reset_usage",
        detail_params={
            "server_id": server_id,
            "old_sub_id": old_sub_id,
            "new_sub_id": new_sub_id,
        },
    )
    logger.info("admin reset usage for server %s: new sub=%s", server_id, new_sub_id)
    return row


async def admin_revoke(db: AsyncSession, server_id: int, *, actor: str = "admin") -> None:
    """Admin revoke: delete NewAPI user + local row (wraps revoke_for_server)."""
    row = await db.get(ServerLlmKey, server_id)
    if row is None:
        raise LlmAdminError("no LLM key for this server")
    newapi_user_id = row.newapi_user_id
    try:
        await newapi_client.delete_user(db, newapi_user_id)
    except Exception:
        logger.warning(
            "admin revoke: failed to delete user %s for server %s",
            newapi_user_id, server_id, exc_info=True,
        )
    await db.delete(row)
    await db.flush()
    await log_manager_activity(
        db,
        actor=actor,
        category="server",
        status="info",
        detail_key="llm.admin.revoke",
        detail_params={
            "server_id": server_id,
            "newapi_user_id": newapi_user_id,
        },
    )
    logger.info("admin revoked LLM for server %s", server_id)


async def update_for_upgrade(
    db: AsyncSession,
    server_id: int,
    new_snapshot: dict[str, Any],
) -> None:
    """Update an existing key's subscription after an upgrade/convert.

    If the new plan has no LLM → revoke. Otherwise, invalidate the old
    subscription and bind a new one from the new plan's newapi_plan_id.
    """
    if not _llm_enabled_in_snapshot(new_snapshot):
        await revoke_for_server(db, server_id)
        return

    new_plan_id = int(new_snapshot.get("newapi_plan_id") or 0)
    if new_plan_id <= 0:
        logger.warning(
            "upgrade server %s: llm_enabled but newapi_plan_id missing",
            server_id,
        )
        return

    row = await db.get(ServerLlmKey, server_id)
    if row is None:
        user_id = 0
        server = await db.get(PteroServer, server_id)
        if server is not None:
            user_id = server.owner_id
        await provision_for_server(db, server_id, user_id, new_snapshot)
        return

    # Invalidate old subscription + bind new
    if row.newapi_subscription_id:
        try:
            await newapi_client.invalidate_subscription(
                db, row.newapi_subscription_id
            )
        except Exception:
            logger.warning(
                "upgrade: failed to invalidate old subscription %s for server %s",
                row.newapi_subscription_id, server_id, exc_info=True,
            )

    try:
        await newapi_client.bind_subscription(
            db, user_id=row.newapi_user_id, plan_id=new_plan_id
        )
        new_sub_id = await newapi_client.get_active_subscription_id(
            db, row.newapi_user_id
        )
        if new_sub_id is None:
            raise newapi_client.NewApiError(
                f"no active subscription after upgrade rebind (user_id={row.newapi_user_id})"
            )
    except Exception:
        logger.warning(
            "upgrade: failed to bind new subscription for server %s "
            "(old sub may already be invalidated; sync job will reconcile)",
            server_id, exc_info=True,
        )
        return

    row.newapi_subscription_id = new_sub_id
    row.newapi_plan_id = new_plan_id
    row.last_synced_at = utc_naive_now()
    if row.status != "disabled":
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
            "new_plan_id": new_plan_id,
            "new_sub_id": new_sub_id,
        },
    )
    logger.info(
        "upgraded LLM subscription for server %s: plan=%s sub=%s",
        server_id, new_plan_id, new_sub_id,
    )
