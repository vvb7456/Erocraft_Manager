"""Daily LLM sync: state alignment, usage sync, monthly quota reset.

Called from the daily lifecycle batch (alongside suspend/delete/trial_expire).
See docs/LLM_FREE_QUOTA_DESIGN.md §10.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime_settings import LLM_SPECS, defaults_for
from app.core.settings_store import get_settings_store
from app.core.time import utc_naive_now
from app.db.models.manager import ServerLlmKey
from app.db.models.pterodactyl import PteroServer
from app.services.llm_provision import newapi_client

logger = logging.getLogger(__name__)


def _is_same_month(a: datetime | None, b: datetime) -> bool:
    if a is None:
        return False
    return a.year == b.year and a.month == b.month


def _should_reset(row: ServerLlmKey, now: datetime) -> bool:
    """Staggered reset: each key resets on its ``reset_day``.
    Catch-up: if the daily batch was down on the key's reset_day, it
    resets on the first run after that day in the same month.
    """
    if _is_same_month(row.last_reset_at, now):
        return False
    return now.day >= row.reset_day


async def _get_endpoint_url(db: AsyncSession) -> str:
    store = get_settings_store()
    values = await store.get_many(db, defaults_for(LLM_SPECS))
    base = str(values.get("NEWAPI_BASE_URL", "")).rstrip("/")
    endpoint = str(values.get("LLM_ST_ENDPOINT_URL", "")).rstrip("/")
    return endpoint or f"{base}/v1"


async def sync_all_usage(db: AsyncSession) -> None:
    """Sync token usage from NewAPI for all active keys."""
    store = get_settings_store()
    settings = await store.get_many(db, defaults_for(LLM_SPECS))
    base_url = str(settings.get("NEWAPI_BASE_URL", "")).rstrip("/")
    if not base_url:
        return

    rows = (
        await db.execute(
            select(ServerLlmKey).where(
                ServerLlmKey.status.in_(
                    ["active", "exhausted", "disabled"]
                )
            )
        )
    ).scalars().all()

    now = utc_naive_now()
    for row in rows:
        try:
            usage = await newapi_client.get_token_usage(row.api_key, base_url)
            row.quota_used = int(usage.get("total_used", 0))
            row.quota_available = int(usage.get("total_available", 0))
            row.last_synced_at = now
            if row.quota_available <= 0 and row.status == "active":
                row.status = "exhausted"
            await db.flush()
        except Exception:
            logger.warning(
                "usage sync failed for server %s (token %s)",
                row.server_id, row.newapi_token_id,
                exc_info=True,
            )


async def sync_all_states(db: AsyncSession) -> None:
    """Align key status with server state (enable/disable tokens)."""
    rows = (
        await db.execute(
            select(ServerLlmKey).where(ServerLlmKey.status != "revoked")
        )
    ).scalars().all()

    for row in rows:
        server = await db.get(PteroServer, row.server_id)
        target_status = "active"
        if server is None:
            target_status = "revoked"
        elif server.is_suspended:
            target_status = "disabled"

        if row.status in ("exhausted",):
            pass
        elif target_status == "revoked":
            try:
                await newapi_client.delete_token(db, row.newapi_token_id)
            except Exception:
                logger.warning(
                    "failed to delete token %s during state sync",
                    row.newapi_token_id, exc_info=True,
                )
            await db.delete(row)
            await db.flush()
            continue
        elif target_status != row.status:
            newapi_status = 1 if target_status == "active" else 2
            try:
                await newapi_client.update_token(
                    db, row.newapi_token_id, status=newapi_status
                )
                row.status = target_status
                await db.flush()
            except Exception:
                logger.warning(
                    "failed to update token %s status", row.newapi_token_id,
                    exc_info=True,
                )


async def reset_monthly_quotas(db: AsyncSession) -> None:
    """Reset token RemainQuota for keys whose reset_day has arrived.

    Uses staggered reset (per-key ``reset_day``, not global 1st) to avoid
    traffic spikes. Catch-up: if the batch was down on a key's reset_day,
    it resets on the next run within the same month.
    Includes active/exhausted/disabled keys — disabled keys get reset too
    (costs nothing; simplifies logic; user gets fresh quota on unfreeze).
    """
    now = utc_naive_now()
    rows = (
        await db.execute(
            select(ServerLlmKey).where(
                ServerLlmKey.status.in_(["active", "exhausted", "disabled"])
            )
        )
    ).scalars().all()

    reset_count = 0
    for row in rows:
        if not _should_reset(row, now):
            continue
        try:
            await newapi_client.update_token(
                db,
                row.newapi_token_id,
                remain_quota=row.quota_grant,
            )
        except Exception:
            logger.warning(
                "failed to reset quota for token %s", row.newapi_token_id,
                exc_info=True,
            )
            continue
        row.quota_available = row.quota_grant
        row.quota_used = 0
        row.last_reset_at = now
        if row.status == "exhausted":
            row.status = "active"
        await db.flush()
        reset_count += 1
    logger.info("monthly quota reset: %d/%d keys reset", reset_count, len(rows))
    if reset_count:
        from app.services.audit import log_manager_activity
        await log_manager_activity(
            db,
            actor="system",
            category="automation",
            status="info",
            detail_key="llm.reset",
            detail_params={"reset_count": reset_count, "total": len(rows)},
        )


async def run_llm_daily_sync(db: AsyncSession) -> None:
    """Entry point — called from the daily lifecycle batch.

    Order: state sync → usage sync → monthly reset. Each step is
    independent and best-effort (failures are logged, not raised).
    """
    store = get_settings_store()
    settings = await store.get_many(db, defaults_for(LLM_SPECS))
    if not bool(settings.get("LLM_ENABLED")):
        return

    logger.info("LLM daily sync started")
    try:
        await sync_all_states(db)
    except Exception:
        logger.warning("LLM state sync failed", exc_info=True)

    try:
        await sync_all_usage(db)
    except Exception:
        logger.warning("LLM usage sync failed", exc_info=True)

    try:
        await reset_monthly_quotas(db)
    except Exception:
        logger.warning("LLM monthly reset failed", exc_info=True)

    await db.commit()
    logger.info("LLM daily sync complete")
