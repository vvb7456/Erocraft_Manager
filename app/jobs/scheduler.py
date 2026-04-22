"""APScheduler wiring for the standalone jobs process."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.runtime_settings import AUTOMATION_SPECS, MONITORING_SPECS, defaults_for
from app.core.settings_store import get_settings_store
from app.db.session import get_session_factory
from app.jobs.tasks.cleanup import CLEANUP_JOB_ID, run_token_cleanup
from app.jobs.tasks.delete import sync_delete_job
from app.jobs.tasks.monitoring import MONITORING_JOB_ID, run_monitoring_collect
from app.jobs.tasks.reminders import sync_reminder_jobs
from app.jobs.tasks.suspend import sync_suspend_job

logger = logging.getLogger(__name__)

SYNC_JOBS_ID = "manager_jobs_sync"
DEFAULT_MONITOR_INTERVAL = 60
_last_settings_signature: tuple[tuple[str, object], ...] | None = None
_last_monitor_interval: int | None = None


def reset_scheduler_sync_state() -> None:
    global _last_settings_signature, _last_monitor_interval
    _last_settings_signature = None
    _last_monitor_interval = None


async def _load_monitor_interval() -> int:
    session_factory = get_session_factory()
    spec = MONITORING_SPECS.get("MONITOR_INTERVAL_SEC")
    if spec is None:
        return DEFAULT_MONITOR_INTERVAL
    async with session_factory() as db:
        values = await get_settings_store().get_many(db, {"MONITOR_INTERVAL_SEC": spec.default_factory()})
    try:
        return int(values.get("MONITOR_INTERVAL_SEC") or DEFAULT_MONITOR_INTERVAL)
    except (TypeError, ValueError):
        return DEFAULT_MONITOR_INTERVAL


def _sync_monitor_job(scheduler: AsyncIOScheduler, interval: int) -> None:
    global _last_monitor_interval
    if interval == _last_monitor_interval:
        return
    scheduler.reschedule_job(MONITORING_JOB_ID, trigger="interval", seconds=interval)
    _last_monitor_interval = interval
    logger.info("monitoring job interval set to %ds", interval)


async def load_automation_settings() -> dict[str, object]:
    session_factory = get_session_factory()
    async with session_factory() as db:
        return await get_settings_store().get_many(db, defaults_for(AUTOMATION_SPECS))


async def sync_managed_jobs(scheduler: AsyncIOScheduler) -> bool:
    global _last_settings_signature

    # Always sync the monitor interval (independent signature).
    try:
        interval = await _load_monitor_interval()
        _sync_monitor_job(scheduler, interval)
    except Exception:
        logger.exception("failed to sync monitor interval")

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
    scheduler.add_job(
        run_monitoring_collect,
        id=MONITORING_JOB_ID,
        trigger="interval",
        seconds=DEFAULT_MONITOR_INTERVAL,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        run_token_cleanup,
        id=CLEANUP_JOB_ID,
        trigger="interval",
        hours=1,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    return scheduler
