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
from app.db.session import get_session_factory

logger = logging.getLogger(__name__)

CLEANUP_JOB_ID = "manager_token_cleanup"

# Tokens are valid for a short window (typically 30min). Keep 24h of history
# for audit then drop. Old rows accumulate as "used" or "expired" otherwise.
TOKEN_RETENTION = timedelta(hours=24)


async def run_token_cleanup() -> None:
    """Delete stale registration / password-reset / email-change rows."""
    session_factory = get_session_factory()
    cutoff = utc_naive_now() - TOKEN_RETENTION
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
