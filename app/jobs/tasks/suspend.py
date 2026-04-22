"""Automated suspend task for expired servers."""

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

SUSPEND_JOB_ID = "auto_suspend_task"


def sync_suspend_job(scheduler: BaseScheduler, settings: Mapping[str, object]) -> None:
    if settings.get("AUTOMATION_SUSPEND_ENABLED"):
        scheduler.add_job(
            run_suspend_task,
            id=SUSPEND_JOB_ID,
            trigger="cron",
            hour=int(settings["AUTOMATION_RUN_HOUR"]),
            minute=int(settings["AUTOMATION_RUN_MINUTE"]),
            timezone=str(settings["TIMEZONE"]),
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=300,
        )
        return

    if scheduler.get_job(SUSPEND_JOB_ID):
        scheduler.remove_job(SUSPEND_JOB_ID)


async def run_suspend_task() -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        await log_manager_activity(
            db,
            actor="system",
            action="automation",
            status="info",
            detail_key="automated_suspend_started",
        )

        try:
            today = await get_job_today(db)
            servers = await server_repository.list_suspend_candidates(db, today)
            if not servers:
                await log_manager_activity(
                    db,
                    actor="system",
                    action="automation",
                    status="info",
                    detail_key="automated_suspend_noop",
                )
                return

            success_count = 0
            failed_ids: list[int] = []
            for server in servers:
                try:
                    await server_lifecycle.suspend_server(db, server.id)
                    success_count += 1
                except LifecycleError:
                    await db.rollback()
                    failed_ids.append(server.id)
                    logger.exception("Failed to suspend server %s in automated task", server.id)

            await log_manager_activity(
                db,
                actor="system",
                action="automation",
                status="success" if success_count or not failed_ids else "failure",
                detail_key="automated_suspend_finished",
                detail_params={"success": success_count, "failed": len(failed_ids), "failed_ids": ", ".join(str(server_id) for server_id in failed_ids)},
            )
        except Exception as exc:
            logger.exception("Automated suspend task failed")
            await log_manager_activity(
                db,
                actor="system",
                action="automation",
                status="failure",
                detail_key="automated_suspend_failed",
                detail_params={"error": str(exc)},
            )
