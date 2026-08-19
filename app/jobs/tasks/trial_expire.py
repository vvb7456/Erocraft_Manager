"""Automated delete task for expired TRIAL servers.

Trial plans bypass the global suspend/delete cadence (AUTOMATION_SUSPEND_*
/ AUTOMATION_DELETE_* / AUTOMATION_DELETE_DAYS): on expiry they are
deleted with zero grace. This task runs on the same daily cron as the
global delete task and removes trial servers whose expiration_date <
today. See ``AGENTS.md`` trial-plan section.
"""

from __future__ import annotations

import logging

from app.db.repositories.servers import server_repository
from app.db.session import get_session_factory
from app.jobs.tasks.common import get_job_today
from app.services.audit import log_manager_activity
from app.services import server_lifecycle
from app.services.server_lifecycle import LifecycleError

logger = logging.getLogger(__name__)


async def run_trial_expire_task() -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        await log_manager_activity(
            db,
            actor="system",
            category="automation",
            status="info",
            detail_key="automated_trial_expire_started",
        )

        try:
            today = await get_job_today(db)
            servers = await server_repository.list_trial_expired(db, today)
            if not servers:
                await log_manager_activity(
                    db,
                    actor="system",
                    category="automation",
                    status="info",
                    detail_key="automated_trial_expire_noop",
                )
                return

            success_count = 0
            failed_ids: list[int] = []
            for server in servers:
                try:
                    await server_lifecycle.delete_server(db, server.id)
                    success_count += 1
                except LifecycleError:
                    await db.rollback()
                    failed_ids.append(server.id)
                    logger.exception(
                        "Failed to delete trial server %s in automated task",
                        server.id,
                    )

            await log_manager_activity(
                db,
                actor="system",
                category="automation",
                status="success" if success_count or not failed_ids else "failure",
                detail_key="automated_trial_expire_finished",
                detail_params={
                    "success": success_count,
                    "failed": len(failed_ids),
                    "failed_ids": ", ".join(str(sid) for sid in failed_ids),
                },
            )
        except Exception as exc:
            logger.exception("Automated trial-expire task failed")
            await log_manager_activity(
                db,
                actor="system",
                category="automation",
                status="failure",
                detail_key="automated_trial_expire_failed",
                detail_params={"error": str(exc)},
            )
