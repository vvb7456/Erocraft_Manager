"""APScheduler wiring for the standalone jobs process."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.base import JobLookupError

from app.core.runtime_settings import AUTOMATION_SPECS, MONITORING_SPECS, defaults_for
from app.core.settings_store import get_settings_store
from app.db.session import get_session_factory
from app.jobs.tasks.billing import (
    APPLY_RETRY_JOB_ID,
    ORDER_CLOSE_JOB_ID,
    ORDER_QUERY_JOB_ID,
    PLACEHOLDER_LEAK_JOB_ID,
    REFUND_RETRY_JOB_ID,
    run_apply_retry,
    run_order_close,
    run_order_query,
    run_placeholder_leak_monitor,
    run_refund_retry,
)
from app.jobs.tasks.certificates import (
    CERT_AUTO_DISPATCH_JOB_ID,
    CERT_DEPLOYMENT_SCAN_JOB_ID,
    CERT_EXPIRY_ALERT_JOB_ID,
    CERT_SOURCE_SCAN_JOB_ID,
    run_cert_auto_dispatch,
    run_cert_deployment_scan,
    run_cert_expiry_alert,
    run_cert_source_scan,
)
from app.jobs.tasks.cleanup import CLEANUP_JOB_ID, run_token_cleanup
from app.jobs.tasks.daily_lifecycle import sync_daily_lifecycle_job
from app.jobs.tasks.force_reinstall_reset import (
    FORCE_REINSTALL_RESET_JOB_ID,
    run_force_reinstall_reset,
)
from app.jobs.tasks.monitoring import MONITORING_JOB_ID, run_monitoring_collect
from app.jobs.tasks.reminders import sync_reminder_jobs
from app.jobs.tasks.server_install_notify import sync_install_notify_job

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
    try:
        scheduler.reschedule_job(MONITORING_JOB_ID, trigger="interval", seconds=interval)
    except JobLookupError:
        # Defensive: should not happen because build_scheduler() registers
        # the job before the first sync, but a future refactor that calls
        # _sync_monitor_job() pre-registration would crash the whole settings
        # sync. Re-add the job in that case. (Audit M9.)
        scheduler.add_job(
            run_monitoring_collect,
            id=MONITORING_JOB_ID,
            trigger="interval",
            seconds=interval,
            replace_existing=True,
        )
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

    sync_daily_lifecycle_job(scheduler, values)
    sync_reminder_jobs(scheduler, values)
    sync_install_notify_job(scheduler, values)
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
    scheduler.add_job(
        run_force_reinstall_reset,
        id=FORCE_REINSTALL_RESET_JOB_ID,
        trigger="interval",
        seconds=30,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        run_cert_source_scan,
        id=CERT_SOURCE_SCAN_JOB_ID,
        trigger="interval",
        minutes=10,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        run_cert_deployment_scan,
        id=CERT_DEPLOYMENT_SCAN_JOB_ID,
        trigger="interval",
        minutes=10,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        run_cert_auto_dispatch,
        id=CERT_AUTO_DISPATCH_JOB_ID,
        trigger="interval",
        minutes=10,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        run_cert_expiry_alert,
        id=CERT_EXPIRY_ALERT_JOB_ID,
        trigger="cron",
        hour=9,
        minute=0,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        run_order_close,
        id=ORDER_CLOSE_JOB_ID,
        trigger="interval",
        minutes=1,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        run_order_query,
        id=ORDER_QUERY_JOB_ID,
        trigger="interval",
        minutes=3,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        run_apply_retry,
        id=APPLY_RETRY_JOB_ID,
        trigger="interval",
        minutes=1,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        run_refund_retry,
        id=REFUND_RETRY_JOB_ID,
        trigger="interval",
        minutes=15,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        run_placeholder_leak_monitor,
        id=PLACEHOLDER_LEAK_JOB_ID,
        trigger="interval",
        hours=1,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )
    return scheduler
