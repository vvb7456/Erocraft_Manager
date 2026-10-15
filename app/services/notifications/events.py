"""Business-specific administrator notifications."""

from datetime import datetime
import hashlib
import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_naive_now, to_iso_z
from app.core.contracts import OperationResult
from app.services.billing.notify import order_apply_alert_context
from app.services.notifications.queue import configuration, enqueue_safely


async def support_message(db: AsyncSession, *, conversation_id: int, message_id: int, username: str) -> None:
    settings = await configuration(db)
    delay = int(settings["NOTIFY_SUPPORT_DELAY"])
    await enqueue_safely(
        db, event_key=f"support:message:{message_id}", category="support", severity="info",
        title=f"客服新消息 · {username}", body="", path=f"/admin/support?conversation={conversation_id}",
        topic=f"support:{conversation_id}", context={"conversation_id": conversation_id, "wecom_template": "support"}, delay=delay, settings=settings,
    )


async def monitoring_alert(db: AsyncSession, *, alert: Any, host_name: str, kind: str, cooldown_min: int = 30) -> None:
    from app.services.email import alert_type_label, severity_label

    now = utc_naive_now()
    window = int((now - alert.created_at).total_seconds()) // max(60, cooldown_min * 60)
    restored = kind == "resolved"
    await enqueue_safely(
        db, event_key=f"monitoring:{alert.id}:{kind}:{0 if restored else window}",
        topic=f"monitoring:{alert.id}", category="monitoring", severity=alert.severity,
        title=f"{'告警恢复' if restored else '监控告警'} · {host_name or alert.host_id}",
        body=f"{alert_type_label(alert.alert_type)}\n{alert.message or ''}",
        path=f"/admin/hosts/{alert.host_id}/overview" if alert.host_id else "/admin/dashboard",
        context={"alert_id": alert.id, "kind": kind, "template": "alert_resolved" if restored else "alert_fired",
                 "wecom_template": "alert_resolved" if restored else "alert_fired",
                 "wecom_variables": {"alert_message": alert.message or "—", "fired_at": to_iso_z(alert.created_at), "resolved_at": to_iso_z(alert.resolved_at) or "—"},
                 "variables": {"node_name": host_name or str(alert.host_id or ""), "node_id": str(alert.host_id or ""),
                     "alert_type": alert.alert_type, "alert_type_label": alert_type_label(alert.alert_type),
                     "severity": alert.severity, "severity_label": severity_label(alert.severity),
                     "message": alert.message or "", "fired_at": str(alert.created_at), "resolved_at": str(alert.resolved_at or "")}},
    )


async def certificate_alert(db: AsyncSession, *, cert: Any, alert_type: str, severity: str, message: str, target: str = "") -> None:
    from app.services.email import alert_type_label

    await enqueue_safely(
        db, event_key=f"certificate:{cert.id}:{alert_type}:{target}:{utc_naive_now().date()}",
        category="certificate", severity=severity, title=f"证书告警 · {cert.name}",
        body=f"{alert_type_label(alert_type)}\n{message}", path="/admin/certificates",
        context={"certificate_id": cert.id, "problem_key": f"certificate:{cert.id}:{alert_type}:{target}",
            "wecom_template": "certificate", "wecom_variables": {"certificate_id": cert.id, "certificate_name": cert.name,
                "alert_type_label": alert_type_label(alert_type), "expires_at": to_iso_z(cert.source_not_after) or "—",
                "target": target or "—", "error": cert.source_last_error or "—"}},
    )


async def billing_incident(db: AsyncSession, incident: Any) -> None:
    labels = {
        "manual_review_required": "订单需要人工审核", "apply_retries_exhausted": "订单开通重试失败",
        "refund_retries_exhausted": "退款重试失败", "placeholder_leak": "订单占位服务器未清理",
        "placeholder_cleanup_failed": "订单占位服务器清理失败",
    }
    body = f"异常记录：{incident.id}"
    if incident.order_id:
        body += f"\n订单 ID：{incident.order_id}"
    if incident.server_id:
        body += f"\n服务器 ID：{incident.server_id}"
    context = {"incident_id": incident.id, "wecom_template": "billing_incident",
        "wecom_variables": {"incident_id": incident.id, "incident_type_label": labels.get(incident.kind, incident.kind),
            "order_id": incident.order_id or "—", "server_id": incident.server_id or "—"}}
    if incident.kind == "apply_retries_exhausted" and incident.order_id:
        from app.db.models.billing import BillingOrder

        order = await db.get(BillingOrder, incident.order_id)
        if order is not None:
            context.update(await order_apply_alert_context(db, order))
    await enqueue_safely(
        db, event_key=f"billing:incident:{incident.id}", category="billing", severity="critical",
        title=labels.get(incident.kind, "订单异常"), body=body + "\n请进入后台查看并处理。",
        path=f"/admin/billing?tab=orders&order={incident.order_id}" if incident.order_id else "/admin/dashboard",
        context=context,
    )


async def billing_apply(db: AsyncSession, order: Any) -> None:
    if order.status == "apply_failed":
        # Terminal failure is delivered with the incident; this hook covers the first retry.
        return
    await enqueue_safely(
        db, event_key=f"billing:apply:{order.id}:{order.status}", category="billing", severity="warning",
        title="订单开通异常", body=f"订单号：{order.order_no}\n重试次数：{order.apply_retry_count}\n请查看订单处理状态。",
        path=f"/admin/billing?tab=orders&order={order.id}",
        context={"order_id": order.id, **await order_apply_alert_context(db, order), "wecom_template": "billing_apply"},
    )


async def audit_failure(db: AsyncSession, *, actor: str, category: str, operation: OperationResult, severity: str = "critical") -> None:
    categories = {"certificate": "证书操作", "automation": "自动化任务", "host_node": "主机操作", "server": "服务器操作", "tunnel": "隧道操作"}
    if category not in categories:
        return
    # Batch email summaries already have per-recipient failure notifications.
    if operation.action in {"automation.reminder", "automation.install_notify"} and operation.error is None:
        return
    if operation.outcome == "success":
        for child in operation.children:
            # Each deployment writes its own audit event before the parent summary.
            if child.action == "certificate.deploy":
                continue
            await audit_failure(db, actor=actor, category=category, operation=child.model_copy(update={"target": child.target or operation.target}), severity="warning")
        return
    if operation.phase == "request":
        return
    labels = {
        "wings.restart": "重启 Wings", "wings.restart_and_verify": "重启并检查 Wings",
        "wings.configuration.update": "更新 Wings 配置", "wings.token.rotate": "更新 Wings 密钥",
        "wings.owner.deauthorize": "撤销旧所有者会话", "tunnel.restart": "重启隧道服务",
        "tunnel.node_cleanup": "清理节点隧道", "certificate.renew": "续签证书", "certificate.deploy": "下发证书",
        "automation.suspend": "自动冻结服务器", "automation.delete": "自动删除服务器",
        "automation.trial_expire": "删除到期试用服务器", "automation.reminder": "发送到期提醒",
        "email.send": "发送邮件", "llm.provision": "开通 LLM 额度", "llm.revoke": "撤销 LLM 额度",
        "llm.subscription.invalidate": "撤销旧 LLM 订阅", "llm.token.enable": "启用 LLM 密钥",
        "server.database.cleanup": "清理服务器远端数据库",
    }
    label = labels.get(operation.action, categories[category])
    target_labels = {"server_id": "服务器", "host_id": "主机", "node_id": "节点", "certificate_id": "证书", "deployment_id": "部署", "requested_server_ids": "服务器", "requested_user_ids": "用户", "recipient": "收件人", "task_name": "任务"}
    target = "，".join(f"{target_labels.get(key, key)}：{value}" for key, value in sorted(operation.target.items()))
    identity = hashlib.sha256(json.dumps(operation.target, sort_keys=True).encode()).hexdigest()[:16]
    issue_key = f"audit:{category}:{operation.action}:{identity}"
    severity = "warning" if operation.succeeded else severity
    # Coalesce recurring failures without copying credential-bearing exception payloads.
    window = int(utc_naive_now().timestamp()) // 1800
    from app.services.notifications.center import record_issue
    if category != "certificate":
        await record_issue(db, key=issue_key, category="system",
            severity=severity, title=f"{label}失败",
            body=f"操作人：{actor}\n关联对象：{target or '—'}", path="/admin/activity-logs")
    await enqueue_safely(
        db, event_key=f"{issue_key}:{window}",
        category="certificate" if category == "certificate" else "system",
        severity=severity, title=f"{label}失败",
        body=f"操作人：{actor}\n{label}失败，请在活动日志中查看详情。" + (f"\n关联对象：{target}" if target else ""),
        path="/admin/activity-logs",
        context={"issue_key": issue_key, "wecom_template": "audit_failure",
            "wecom_variables": {"actor": actor, "operation": label, "status_label": "失败", "target": target or "—"}},
    )


async def task_failure(job_id: str, when: datetime, error_type: str) -> None:
    from app.db.session import get_session_factory

    try:
        async with get_session_factory()() as db:
            from app.services.notifications.center import record_issue
            await record_issue(db, key=f"task:{job_id}", category="system", severity="critical",
                title="后台任务运行异常", body=f"任务：{job_id}\n异常类型：{error_type}", path="/admin/activity-logs")
            await enqueue_safely(
                db, event_key=f"task:{job_id}:{int(when.timestamp()) // 1800}", category="system", severity="critical",
                title="后台任务运行异常", body=f"任务：{job_id}\n异常类型：{error_type}\n请检查后台运行日志。", path="/admin/activity-logs",
                context={"issue_key": f"task:{job_id}", "wecom_template": "task_failure", "wecom_variables": {"job_id": job_id, "error_type": error_type}},
            )
            await db.commit()
    except Exception as exc:
        logging.getLogger(__name__).error("task notification failed job=%s error_type=%s", job_id, type(exc).__name__)


async def task_recovered(job_id: str) -> None:
    from sqlalchemy import update
    from app.db.models.notifications import NotificationIssue
    from app.db.session import get_session_factory
    try:
        async with get_session_factory()() as db:
            await db.execute(update(NotificationIssue).where(NotificationIssue.key == f"task:{job_id}", NotificationIssue.resolved_at.is_(None)).values(resolved_at=utc_naive_now()))
            await db.commit()
    except Exception:
        logging.getLogger(__name__).exception("task recovery update failed job=%s", job_id)
