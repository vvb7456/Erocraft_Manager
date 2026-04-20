"""APScheduler wiring for the standalone jobs process."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.runtime_settings import AUTOMATION_SPECS, defaults_for
from app.core.settings_store import get_settings_store
from app.db.session import get_session_factory
from app.jobs.tasks.delete import sync_delete_job
from app.jobs.tasks.reminders import sync_reminder_jobs
from app.jobs.tasks.suspend import sync_suspend_job

logger = logging.getLogger(__name__)

SYNC_JOBS_ID = "manager_jobs_sync"
_last_settings_signature: tuple[tuple[str, object], ...] | None = None


def reset_scheduler_sync_state() -> None:
    global _last_settings_signature
    _last_settings_signature = None


async def load_automation_settings() -> dict[str, object]:
    session_factory = get_session_factory()
    async with session_factory() as db:
        return await get_settings_store().get_many(db, defaults_for(AUTOMATION_SPECS))


async def sync_managed_jobs(scheduler: AsyncIOScheduler) -> bool:
    global _last_settings_signature

    values = await load_automation_settings()
    signature = tuple(sorted(values.items()))
    if signature == _last_settings_signature:
        return False

    sync_suspend_job(scheduler, values)
    sync_delete_job(scheduler, values)
    sync_reminder_jobs(scheduler, values)
    _last_settings_signature = signature
    logger.info("manager-jobs schedule updated from runtime settings")
    return True


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        sync_managed_jobs,
        id=SYNC_JOBS_ID,
        trigger="interval",
        seconds=60,
        kwargs={"scheduler": scheduler},
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=30,
    )
    return scheduler
