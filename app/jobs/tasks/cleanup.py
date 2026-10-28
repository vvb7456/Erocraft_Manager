"""Periodic cleanup tasks for short-lived manager tables."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete

from app.core.time import utc_naive_now
from app.db.models.manager import (
    ManagerEmailChange,
    ManagerPasswordReset,
    ManagerPendingRegistration,
)
from app.db.models.monitoring import HostMetrics, HostProbeResult
from app.db.models.miniprogram import MiniProgramSession
from app.db.models.notifications import NotificationDelivery, NotificationIssue
from app.db.session import get_session_factory

logger = logging.getLogger(__name__)

CLEANUP_JOB_ID = "manager_token_cleanup"

# Tokens are valid for a short window (typically 30min). Keep 24h of history
# for audit then drop. Old rows accumulate as "used" or "expired" otherwise.
TOKEN_RETENTION = timedelta(hours=24)



async def run_token_cleanup() -> None:
    """Delete stale registration / password-reset / email-change rows
    plus monitoring time-series older than the retention window."""
    session_factory = get_session_factory()
    cutoff = utc_naive_now() - TOKEN_RETENTION
    async with session_factory() as db:
        from app.core.settings_store import get_settings_store
        metrics_cutoff = utc_naive_now() - timedelta(days=int(await get_settings_store().get(db, "MONITOR_RETENTION_DAYS", 30)))
        try:
            res_reg = await db.execute(
                delete(ManagerPendingRegistration).where(
                    ManagerPendingRegistration.created_at < cutoff
                )
            )
            res_pwd = await db.execute(
                delete(ManagerPasswordReset).where(
                    ManagerPasswordReset.created_at < cutoff
                )
            )
            res_eml = await db.execute(
                delete(ManagerEmailChange).where(
                    ManagerEmailChange.created_at < cutoff
                )
            )
            await db.commit()
            logger.info(
                "token cleanup: deleted %s pending registrations, %s password resets, %s email changes",
                res_reg.rowcount,
                res_pwd.rowcount,
                res_eml.rowcount,
            )
            await db.execute(delete(MiniProgramSession).where(MiniProgramSession.expires_at < utc_naive_now()))
            await db.execute(delete(NotificationDelivery).where(
                NotificationDelivery.created_at < utc_naive_now() - timedelta(days=90),
                NotificationDelivery.status.in_(("sent", "skipped", "failed")),
            ))
            await db.execute(delete(NotificationIssue).where(NotificationIssue.resolved_at < utc_naive_now() - timedelta(days=90)))
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("token cleanup failed")

        try:
            res_hm = await db.execute(
                delete(HostMetrics)
                .where(HostMetrics.ts < metrics_cutoff)
                .execution_options(synchronize_session=False)
            )
            res_hp = await db.execute(
                delete(HostProbeResult)
                .where(HostProbeResult.ts < metrics_cutoff)
                .execution_options(synchronize_session=False)
            )
            await db.commit()
            logger.info(
                "monitoring cleanup: deleted %s host_metrics, %s host_probes (cutoff=%s)",
                res_hm.rowcount,
                res_hp.rowcount,
                metrics_cutoff.isoformat(),
            )
        except Exception:
            await db.rollback()
            logger.exception("monitoring cleanup failed")
