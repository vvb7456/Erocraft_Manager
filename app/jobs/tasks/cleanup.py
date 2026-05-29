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
from app.db.session import get_session_factory

logger = logging.getLogger(__name__)

CLEANUP_JOB_ID = "manager_token_cleanup"

# Tokens are valid for a short window (typically 30min). Keep 24h of history
# for audit then drop. Old rows accumulate as "used" or "expired" otherwise.
TOKEN_RETENTION = timedelta(hours=24)

# Monitoring time-series: the admin UI only exposes windows up to 7d
# (see app/api/routers/monitoring.py::_WINDOW_TO_SECONDS). Keep 14d of
# raw 1-minute samples as buffer for ad-hoc SQL debugging, then drop.
# At 5 hosts × 1/min daily cleanup removes ~7200 rows — single-shot
# DELETE is fast enough.
METRICS_RETENTION = timedelta(days=14)


async def run_token_cleanup() -> None:
    """Delete stale registration / password-reset / email-change rows
    plus monitoring time-series older than the retention window."""
    session_factory = get_session_factory()
    cutoff = utc_naive_now() - TOKEN_RETENTION
    metrics_cutoff = utc_naive_now() - METRICS_RETENTION
    async with session_factory() as db:
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

