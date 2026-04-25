"""Scheduled certificate management tasks."""

from __future__ import annotations

import logging

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
