"""Certificate alert checks and email notifications."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime_settings import CERTIFICATE_SPECS, defaults_for
from app.core.settings_store import get_settings_store
from app.core.time import utc_naive_now
from app.db.models.manager import ManagerCertDeployment, ManagerCertificate, ManagerHost
from app.db.models.pterodactyl import PteroUser
from app.services.audit import log_manager_activity
from app.services.email import send_alert_email

logger = logging.getLogger(__name__)


def _parse_admin_ids(raw: Any) -> list[int]:
    return [int(x) for x in str(raw or "").split(",") if x.strip().isdigit()]


async def _resolve_admin_emails(db: AsyncSession, admin_ids: list[int]) -> list[tuple[int, str]]:
    if admin_ids:
        stmt = select(PteroUser.id, PteroUser.email).where(
            PteroUser.id.in_(admin_ids),
            PteroUser.root_admin.is_(True),
        )
    else:
        stmt = select(PteroUser.id, PteroUser.email).where(PteroUser.root_admin.is_(True))
    result = await db.execute(stmt)
    return [(rid, email) for rid, email in result.all() if email]


async def _notify(
    db: AsyncSession,
    *,
    recipients: list[tuple[int, str]],
    cert: ManagerCertificate,
    alert_type: str,
    severity: str,
    message: str,
) -> int:
    sent = 0
    now = utc_naive_now()
    for _uid, email in recipients:
        try:
            ok, err = await send_alert_email(
                db,
                recipient_email=email,
                node_name=cert.name,
                node_id=None,
                alert_type=alert_type,
                severity=severity,
                message=message,
                fired_at=now,
                kind="fired",
            )
        except Exception as exc:  # noqa: BLE001
            ok, err = False, str(exc)
        if ok:
            sent += 1
        else:
            logger.warning(
                "cert alert email failed cert_id=%s recipient=%s: %s",
                cert.id,
                email,
                err,
            )
    if sent:
        await log_manager_activity(
            db,
            actor="system",
            action="cert_alert",
            status="success",
            detail_key="cert.alert.sent",
            detail_params={
                "certificate_id": cert.id,
                "alert_type": alert_type,
                "severity": severity,
                "sent": sent,
            },
        )
    return sent


async def run_certificate_alerts(db: AsyncSession) -> list[dict[str, Any]]:
    """Evaluate certificate alert conditions and send admin emails.

    This is intentionally stateless in the first backend pass. The scheduler
    runs it daily, so each still-active condition can produce at most one
    batch per day.
    """
    settings = await get_settings_store().get_many(
        db,
        defaults_for(CERTIFICATE_SPECS),
    )
    if not bool(settings.get("CERT_ALERT_EMAIL_ENABLED", True)):
        return []

    recipients = await _resolve_admin_emails(
        db,
        _parse_admin_ids(settings.get("CERT_ALERT_EMAIL_ADMIN_IDS")),
    )
    if not recipients:
        return []

    now = utc_naive_now()
    out: list[dict[str, Any]] = []

    certs = (
        await db.execute(
            select(ManagerCertificate)
            .where(ManagerCertificate.enabled.is_(True))
            .order_by(ManagerCertificate.id)
        )
    ).scalars().all()

    for cert in certs:
        if cert.source_not_after is None:
            sent = await _notify(
                db,
                recipients=recipients,
                cert=cert,
                alert_type="cert_source_unknown",
                severity="warning",
                message=f"Certificate source has no known expiry. Last error: {cert.source_last_error or '-'}",
            )
            out.append({"certificate_id": cert.id, "type": "source_unknown", "sent": sent})
        else:
            days_left = (cert.source_not_after - now).days
            if days_left <= int(cert.alert_threshold_days or 14):
                severity = "critical" if cert.source_not_after <= now else "warning"
                sent = await _notify(
                    db,
                    recipients=recipients,
                    cert=cert,
                    alert_type="cert_source_expiring",
                    severity=severity,
                    message=(
                        f"Certificate source expires at {cert.source_not_after} UTC "
                        f"({days_left} days left)."
                    ),
                )
                out.append({"certificate_id": cert.id, "type": "source_expiring", "sent": sent})

        deployments = (
            await db.execute(
                select(ManagerCertDeployment, ManagerHost)
                .join(ManagerHost, ManagerHost.id == ManagerCertDeployment.host_id)
                .where(ManagerCertDeployment.certificate_id == cert.id)
                .where(ManagerCertDeployment.status.in_(("outdated", "unreachable")))
            )
        ).all()
        for dep, host in deployments:
            check_at = dep.last_check_at or dep.last_deploy_attempt_at
            if check_at and (now - check_at) < timedelta(hours=1):
                continue
            sent = await _notify(
                db,
                recipients=recipients,
                cert=cert,
                alert_type=(
                    "cert_deployment_unreachable"
                    if dep.status == "unreachable"
                    else "cert_deployment_outdated"
                ),
                severity="warning",
                message=(
                    f"Deployment {dep.id} on host {host.name} "
                    f"(host_id={host.id}) is {dep.status}. "
                    f"Last check error: {dep.last_check_error or '-'}"
                ),
            )
            out.append({
                "certificate_id": cert.id,
                "deployment_id": dep.id,
                "type": dep.status,
                "sent": sent,
            })
    return out
