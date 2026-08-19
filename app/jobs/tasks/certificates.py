"""Scheduled certificate management tasks."""

from __future__ import annotations

import logging
from typing import Mapping

from apscheduler.schedulers.base import BaseScheduler

from app.db.session import get_session_factory
from app.services.cert_manager.alerter import run_certificate_alerts
from app.services.cert_manager.deployment_scanner import scan_all_deployments
from app.services.cert_manager.dispatcher import dispatch_pending_deployments
from app.services.cert_manager.source_scanner import scan_all_certificate_sources

logger = logging.getLogger(__name__)

CERT_SOURCE_SCAN_JOB_ID = "cert_source_scan"
CERT_DEPLOYMENT_SCAN_JOB_ID = "cert_deployment_scan"
CERT_AUTO_DISPATCH_JOB_ID = "cert_auto_dispatch"
CERT_EXPIRY_ALERT_JOB_ID = "cert_expiry_alert"

# Local hour to fire the daily certificate expiry alert scan. Mirrors the
# daily lifecycle batch's use of AUTOMATION_RUN_HOUR but kept independent so
# cert alerts can run at a different time without coupling to server
# lifecycle automation.
_CERT_ALERT_HOUR = 9
_CERT_ALERT_MINUTE = 0


def sync_cert_expiry_alert_job(
    scheduler: BaseScheduler, settings: Mapping[str, object]
) -> None:
    """Register the daily cert expiry alert cron in the runtime TIMEZONE.

    Unlike the interval-based cert scans (which are timezone-agnostic), this
    cron must fire at a specific local wall-clock hour, so it inherits the
    scheduler's UTC default unless we pass ``timezone``. Reading TIMEZONE
    from runtime settings keeps the trigger hour aligned with the operator's
    configured timezone (default Asia/Shanghai).
    """
    scheduler.add_job(
        run_cert_expiry_alert,
        id=CERT_EXPIRY_ALERT_JOB_ID,
        trigger="cron",
        hour=_CERT_ALERT_HOUR,
        minute=_CERT_ALERT_MINUTE,
        timezone=str(settings["TIMEZONE"]),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )


async def run_cert_source_scan() -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        results = await scan_all_certificate_sources(db)
        logger.info("certificate source scan completed (%d rows)", len(results))


async def run_cert_deployment_scan() -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        results = await scan_all_deployments(db)
        logger.info("certificate deployment scan completed (%d rows)", len(results))


async def run_cert_auto_dispatch() -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        await scan_all_certificate_sources(db)
        results = await dispatch_pending_deployments(db, actor="system")
        logger.info("certificate auto-dispatch completed (%d deployments)", len(results))


async def run_cert_expiry_alert() -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        results = await run_certificate_alerts(db)
        logger.info("certificate alert check completed (%d events)", len(results))
