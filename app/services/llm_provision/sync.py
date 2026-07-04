"""Daily LLM sync: state alignment.

Called from the daily lifecycle batch. NewAPI's background task handles
subscription quota reset (AmountUsed → 0 on NextResetTime), so Manager
no longer needs ``reset_monthly_quotas`` or ``sync_all_usage``.

The only remaining job is ``sync_all_states``: align key status with
server state — suspended → disable token; deleted → revoke (delete user).
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime_settings import LLM_SPECS, defaults_for
from app.core.settings_store import get_settings_store
from app.db.models.manager import ServerLlmKey
from app.db.models.pterodactyl import PteroServer
from app.services.llm_provision import newapi_client

logger = logging.getLogger(__name__)


async def sync_all_states(db: AsyncSession) -> None:
    """Align key status with server state (enable/disable tokens).

    * Server deleted → delete NewAPI user + local row (revoke).
    * Server suspended → disable token.
    * Server active → enable token.
    """
    rows = (
        await db.execute(
            select(ServerLlmKey).where(ServerLlmKey.status != "revoked")
        )
    ).scalars().all()

    for row in rows:
        server = await db.get(PteroServer, row.server_id)
        if server is None:
            # Server gone — revoke (delete user, cascade tokens+subs)
            try:
                await newapi_client.delete_user(db, row.newapi_user_id)
            except Exception:
                logger.warning(
                    "sync: failed to delete user %s for server %s",
                    row.newapi_user_id, row.server_id, exc_info=True,
                )
            await db.delete(row)
            await db.flush()
            continue

        target_status = "disabled" if server.is_suspended else "active"
        if row.status == target_status:
            continue

        newapi_status = 1 if target_status == "active" else 2
        try:
            await newapi_client.update_token(
                db,
                access_token=row.newapi_user_access_token,
                user_id=row.newapi_user_id,
                token_id=row.newapi_token_id,
                status=newapi_status,
            )
            row.status = target_status
            await db.flush()
        except Exception:
            logger.warning(
                "sync: failed to update token %s status for server %s",
                row.newapi_token_id, row.server_id, exc_info=True,
            )


async def run_llm_daily_sync(db: AsyncSession) -> None:
    """Entry point — called from the daily lifecycle batch.

    Only state sync remains. NewAPI handles quota reset and usage tracking.
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

    await db.commit()
    logger.info("LLM daily sync complete")
