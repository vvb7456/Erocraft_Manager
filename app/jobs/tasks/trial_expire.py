"""Automated delete task for expired TRIAL servers.

Trial plans bypass the global suspend/delete cadence (AUTOMATION_SUSPEND_*
/ AUTOMATION_DELETE_* / AUTOMATION_DELETE_DAYS): on expiry they are
deleted with zero grace. This task runs on the same daily cron as the
global delete task and removes trial servers whose expiration_date <
today. See ``AGENTS.md`` trial-plan section.
"""

from __future__ import annotations

import logging
from typing import Mapping

from apscheduler.schedulers.base import BaseScheduler

from app.db.repositories.servers import server_repository
from app.db.session import get_session_factory
from app.jobs.tasks.common import get_job_today
from app.services.audit import log_manager_activity
from app.services import server_lifecycle
from app.services.server_lifecycle import LifecycleError

logger = logging.getLogger(__name__)

TRIAL_EXPIRE_JOB_ID = "auto_trial_expire_task"


def sync_trial_expire_job(scheduler: BaseScheduler, settings: Mapping[str, object]) -> None:
    """Trial expiry always runs — it's not gated by AUTOMATION_DELETE_ENABLED
    because trial plans have their own mandatory zero-grace deletion policy
    independent of the global delete toggle."""
    scheduler.add_job(
        run_trial_expire_task,
        id=TRIAL_EXPIRE_JOB_ID,
        trigger="cron",
        hour=int(str(settings["AUTOMATION_RUN_HOUR"])),
        minute=int(str(settings["AUTOMATION_RUN_MINUTE"])),
        timezone=str(settings["TIMEZONE"]),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )


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
