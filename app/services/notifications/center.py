"""Current problems are derived from business state, independently of deliveries."""

from datetime import timedelta
from typing import Any

from sqlalchemy import select, case
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_naive_now, to_iso_z
from app.db.models.manager import ManagerCertificate, ManagerCertDeployment, ManagerHost
from app.db.models.notifications import NotificationIssue
from app.services.email import alert_type_label


async def record_issue(db: AsyncSession, *, key: str, category: str, severity: str, title: str, body: str, path: str) -> None:
    now = utc_naive_now()
    stmt = insert(NotificationIssue).values(key=key[:190], category=category, severity=severity,
        title=title[:200], body=body[:8000], path=path, created_at=now, updated_at=now)
    await db.execute(stmt.on_duplicate_key_update([
        ("acknowledged_at", case((NotificationIssue.resolved_at.isnot(None), None), else_=NotificationIssue.acknowledged_at)),
        ("title", stmt.inserted.title), ("body", stmt.inserted.body), ("severity", stmt.inserted.severity),
        ("updated_at", now), ("resolved_at", None),
    ]))


async def certificate_problems(db: AsyncSession) -> list[dict[str, Any]]:
    now = utc_naive_now()
    result = []
    certs = (await db.scalars(select(ManagerCertificate).where(ManagerCertificate.enabled.is_(True)))).all()
    for cert in certs:
        kind, message, severity = "", "", "warning"
        if cert.source_last_error or cert.source_not_after is None:
            kind, message = "cert_source_unknown", cert.source_last_error or "证书源有效期未知"
        elif cert.source_not_after <= now + timedelta(days=cert.alert_threshold_days):
            kind, message = "cert_source_expiring", f"证书到期时间：{to_iso_z(cert.source_not_after)}"
            severity = "critical" if cert.source_not_after <= now else "warning"
        if kind:
            result.append({"key": f"certificate:{cert.id}:{kind}:", "category": "certificate", "severity": severity,
                "title": f"{cert.name} · {alert_type_label(kind)}", "body": message, "path": "/admin/certificates",
                "created_at": cert.updated_at, "variables": {"certificate_id": cert.id, "certificate_name": cert.name,
                    "alert_type_label": alert_type_label(kind), "expires_at": to_iso_z(cert.source_not_after) or "—",
                    "target": "—", "error": cert.source_last_error or "—"}})
    by_id = {c.id: c for c in certs}
    rows = (await db.execute(select(ManagerCertDeployment, ManagerHost.name).join(ManagerHost, ManagerHost.id == ManagerCertDeployment.host_id)
        .where(ManagerCertDeployment.certificate_id.in_(by_id), ManagerCertDeployment.status != "synced"))).all()
    for dep, host in rows:
        if not dep.unhealthy_since or now - dep.unhealthy_since < timedelta(hours=1):
            continue
        kind = "cert_deployment_outdated" if dep.status == "outdated" else "cert_deployment_unreachable"
        cert = by_id[dep.certificate_id]
        result.append({"key": f"certificate:{dep.certificate_id}:{kind}:{dep.id}", "category": "certificate", "severity": "warning",
            "title": f"{host} · {alert_type_label(kind)}", "body": dep.last_check_error or dep.status,
            "path": "/admin/certificates", "created_at": dep.unhealthy_since,
            "variables": {"certificate_id": cert.id, "certificate_name": cert.name, "alert_type_label": alert_type_label(kind),
                "expires_at": to_iso_z(cert.source_not_after) or "—", "target": host, "error": dep.last_check_error or "—"}})
    return result


async def current_problems(db: AsyncSession) -> list[dict[str, Any]]:
    from app.db.models.monitoring import HostAlert
    from app.db.models.billing import BillingIncident
    items = await certificate_problems(db)
    rows = (await db.execute(select(HostAlert, ManagerHost.name).outerjoin(ManagerHost, ManagerHost.id == HostAlert.host_id)
        .where(HostAlert.resolved_at.is_(None)))).all()
    for alert, host in rows:
        items.append({"key": f"monitoring:{alert.id}", "category": "monitoring", "severity": alert.severity,
            "title": f"{host or alert.host_id} · {alert_type_label(alert.alert_type)}", "body": alert.message or "",
            "path": f"/admin/hosts/{alert.host_id}/overview" if alert.host_id else "/admin/dashboard",
            "created_at": alert.created_at, "acknowledged_at": alert.acknowledged_at, "muted_until": alert.muted_until})
    for incident in (await db.execute(select(BillingIncident.id, BillingIncident.kind, BillingIncident.order_id, BillingIncident.detected_at).where(BillingIncident.status == "open"))).all():
        labels = {"manual_review_required": "订单需要人工审核", "apply_retries_exhausted": "订单开通重试失败", "refund_retries_exhausted": "退款重试失败", "placeholder_leak": "订单占位服务器未清理", "placeholder_cleanup_failed": "订单占位服务器清理失败"}
        items.append({"key": f"billing:{incident.id}", "category": "billing", "severity": "critical",
            "title": f"订单异常 · {incident.order_id or incident.id}", "body": labels.get(incident.kind, incident.kind),
            "path": f"/admin/billing?tab=orders&order={incident.order_id}" if incident.order_id else "/admin/billing",
            "created_at": incident.detected_at})
    states = {r.key: r for r in (await db.scalars(select(NotificationIssue))).all()}
    for row in states.values():
        if row.category == "system" and row.resolved_at is None:
            items.append({"key": row.key, "category": row.category, "severity": row.severity, "title": row.title,
                "body": row.body, "path": row.path, "created_at": row.created_at})
    now = utc_naive_now()
    for item in items:
        state = states.get(item["key"])
        ack = item.get("acknowledged_at") or (state.acknowledged_at if state else None)
        muted = item.get("muted_until") or (state.muted_until if state else None)
        item["state"] = "muted" if muted and muted > now else "acknowledged" if ack else "open"
        item["acknowledged_at"], item["muted_until"] = to_iso_z(ack), to_iso_z(muted)
        item["created_at"] = to_iso_z(item["created_at"])
    return sorted(items, key=lambda x: (x["severity"] != "critical", x["created_at"] or ""))
