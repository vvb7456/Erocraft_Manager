"""Transactional enqueue, per-recipient retries and cross-process dispatch exclusion."""

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import case, func, select, text
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime_settings import NOTIFICATION_SPECS, SETTINGS_SPECS, defaults_for
from app.core.settings_store import get_settings_store
from app.core.time import utc_naive_now
from app.db.models.notifications import NotificationDelivery
from app.db.session import get_engine
from app.services.notifications import wecom
from app.services.notifications.policy import load_policy

logger = logging.getLogger(__name__)
RANK = {"info": 0, "warning": 1, "critical": 2}
MAX_ATTEMPTS = 8


async def targets(db: AsyncSession, category: str, severity: str, context: dict, settings: dict) -> dict[str, list[str]]:
    policy = await load_policy(db)
    rule = policy.routes[category]
    minimum: str = rule.min_severity
    email_enabled, email_resolved = rule.email, rule.email_resolved
    email_group = next(g for g in policy.groups if g.id == rule.email_group)
    admin_ids = None if email_group.all_admins else email_group.admin_ids
    if category == "monitoring" and context.get("alert_id"):
        from app.db.models.monitoring import HostAlert
        from app.db.models.manager import HostAlertSettings
        alert = await db.get(HostAlert, context["alert_id"])
        host = await db.get(HostAlertSettings, alert.host_id) if alert and alert.host_id else None
        if host:
            minimum = host.min_severity or minimum
            if host.email_enabled is not None:
                email_enabled = host.email_enabled
            if host.notify_resolve is not None:
                email_resolved = host.notify_resolve
            if host.email_recipients is not None:
                admin_ids = host.email_recipients or None
    if category != "support" and RANK.get(severity, 0) < RANK.get(minimum, 1):
        return {}
    resolved = context.get("kind") == "resolved"
    result = {}
    if rule.wecom and settings.get("WECOM_ENABLED") and (not resolved or rule.wecom_resolved):
        group = next(g for g in policy.groups if g.id == rule.wecom_group)
        result["wecom"] = group.wecom_ids
    if email_enabled and (not resolved or email_resolved):
        from app.db.models.pterodactyl import PteroUser
        stmt = select(PteroUser.email).where(PteroUser.root_admin.is_(True))
        if admin_ids is not None:
            stmt = stmt.where(PteroUser.id.in_(admin_ids))
        result["email"] = list(dict.fromkeys(e for e in (await db.scalars(stmt)).all() if e))
    return result


async def configuration(db: AsyncSession) -> dict[str, Any]:
    return await get_settings_store().get_many(db, defaults_for(NOTIFICATION_SPECS))


async def enqueue(
    db: AsyncSession, *, event_key: str, category: str, severity: str,
    title: str, body: str, path: str, topic: str = "", context: dict[str, Any] | None = None,
    delay: int = 0, settings: dict[str, Any] | None = None,
) -> list[int]:
    values = settings if settings is not None else await configuration(db)
    destinations = await targets(db, category, severity, context or {}, values)
    now = utc_naive_now()
    keys = []
    for channel, members in destinations.items():
        gateway = wecom.gateway_key(values) if channel == "wecom" else "smtp"
        if channel == "wecom" and members:
            wecom.validate(values, members)
        for recipient in members:
            key = hashlib.sha256(f"{gateway}:{recipient}:{event_key}".encode()).hexdigest()
            keys.append(key)
            stmt = insert(NotificationDelivery).values(
                dedup_key=key, gateway_key=gateway, channel=channel, recipient=recipient,
                category=category, severity=severity, title=title[:200], body=body[:8000], path=path[:500],
                topic=(topic or event_key)[:120], context=context or {}, status="pending", attempts=0,
                created_at=now, available_at=now + timedelta(seconds=delay),
            )
            await db.execute(stmt.on_duplicate_key_update(dedup_key=stmt.inserted.dedup_key))
    return list((await db.scalars(select(NotificationDelivery.id).where(NotificationDelivery.dedup_key.in_(keys)))).all())


async def enqueue_safely(db: AsyncSession, **kwargs: Any) -> list[int]:
    # A notification failure must not roll back a payment, chat message or host sample.
    try:
        async with db.begin_nested():
            return await enqueue(db, **kwargs)
    except Exception as exc:
        logger.error("notification enqueue failed category=%s error_type=%s", kwargs.get("category"), type(exc).__name__)
        return []


async def prepare(db: AsyncSession, row: NotificationDelivery, settings: dict[str, Any]) -> str | datetime | None:
    """Return a skip reason or mute deadline; None means ready to send."""
    destinations = await targets(db, row.category, row.severity, row.context, settings)
    if row.recipient not in destinations.get(row.channel, []):
        return "该渠道已关闭或接收规则已变更"
    if row.channel == "wecom" and row.gateway_key != wecom.gateway_key(settings):
        return "应用或接收人配置已变更"
    issue_key = row.context.get("issue_key") or row.context.get("problem_key")
    if row.category == "billing" and row.context.get("incident_id"):
        issue_key = f"billing:{row.context['incident_id']}"
    if issue_key:
        from app.db.models.notifications import NotificationIssue
        issue = await db.get(NotificationIssue, issue_key)
        if issue and issue.resolved_at:
            return "问题已处理"
        if issue and issue.muted_until and issue.muted_until > utc_naive_now():
            return issue.muted_until
    if row.category == "support":
        from app.db.models.pterodactyl import PteroUser
        from app.db.models.support import SupportConversation, SupportMessage

        conversation = await db.get(SupportConversation, row.context.get("conversation_id"))
        if conversation is None:
            return "会话已删除"
        cursor = conversation.admin_read_id
        previous = await db.scalar(select(func.max(NotificationDelivery.context["message_id"].as_integer())).where(
            NotificationDelivery.topic == row.topic, NotificationDelivery.recipient == row.recipient,
            NotificationDelivery.gateway_key == row.gateway_key, NotificationDelivery.status == "sent",
        ))
        if previous:
            cursor = max(cursor, int(previous))
        query = select(SupportMessage).where(
            SupportMessage.conversation_id == conversation.id, SupportMessage.is_admin.is_(False),
            SupportMessage.id > cursor,
        )
        if row.attempts and row.context.get("message_id"):
            query = query.where(SupportMessage.id <= int(row.context["message_id"]))
        messages = list((await db.scalars(query.order_by(SupportMessage.id.desc()).limit(5))).all())
        if not messages:
            return "消息已读或已通过企业微信提醒"
        if row.attempts:
            # Preserve the original content for WeCom's duplicate check after an ambiguous timeout.
            return None
        count = await db.scalar(select(func.count()).select_from(SupportMessage).where(
            SupportMessage.conversation_id == conversation.id, SupportMessage.is_admin.is_(False), SupportMessage.id > cursor,
        ))
        username = await db.scalar(select(PteroUser.username).where(PteroUser.id == conversation.user_id))
        row.title = f"客服新消息 · {username or conversation.user_id}"[:200]
        row.body = f"{count} 条未读消息\n" + "\n".join((message.content[:220] + (" [截图]" if message.image_type else "")) for message in reversed(messages))
        row.context = {**row.context, "message_id": messages[0].id}
    elif row.category == "monitoring":
        from app.db.models.monitoring import HostAlert

        alert = await db.get(HostAlert, row.context.get("alert_id"))
        if alert is None:
            return "告警记录已删除"
        if row.context.get("kind") == "fired" and alert.resolved_at:
            return "告警已恢复"
        if row.context.get("kind") == "fired" and alert.muted_until and alert.muted_until > utc_naive_now():
            return alert.muted_until
        if row.context.get("kind") == "fired":
            newer = await db.scalar(select(NotificationDelivery.id).where(
                NotificationDelivery.topic == row.topic, NotificationDelivery.recipient == row.recipient,
                NotificationDelivery.gateway_key == row.gateway_key, NotificationDelivery.status == "sent",
                NotificationDelivery.created_at > row.created_at,
            ).limit(1))
            if newer:
                return "已发送较新的告警提醒"
        if row.context.get("kind") == "resolved":
            notified = await db.scalar(select(NotificationDelivery.id).where(
                NotificationDelivery.topic == row.topic, NotificationDelivery.recipient == row.recipient,
                NotificationDelivery.gateway_key == row.gateway_key, NotificationDelivery.status == "sent",
                NotificationDelivery.context["kind"].as_string() == "fired",
            ).limit(1))
            if not notified:
                return "该告警未向此接收人发送"
    elif row.category == "billing":
        from app.db.models.billing import BillingIncident, BillingOrder
        if row.context.get("incident_id"):
            incident = await db.get(BillingIncident, row.context["incident_id"])
            if incident is None or incident.status != "open":
                return "订单异常已处理"
        elif row.context.get("order_id"):
            order = await db.get(BillingOrder, row.context["order_id"])
            if order is None or order.status not in {"processing", "apply_failed"}:
                return "订单状态已更新"
    elif row.category == "certificate" and row.context.get("certificate_id"):
        from app.services.notifications.center import certificate_problems
        problems = await certificate_problems(db)
        if row.context.get("problem_key") not in {p["key"] for p in problems}:
            return "证书异常已恢复"
    return None


async def _dispatch(db: AsyncSession, row_id: int) -> None:
    settings = await configuration(db)
    row = await db.get(NotificationDelivery, row_id)
    if row is None or row.status not in {"pending", "sending"} or row.available_at > utc_naive_now():
        return
    reason = await prepare(db, row, settings)
    if isinstance(reason, datetime):
        row.status, row.available_at, row.last_error = "pending", reason, "告警已临时静默"
        await db.commit()
        return
    if reason:
        row.status, row.last_error = "skipped", reason
        await db.commit()
        return
    now = utc_naive_now()
    if row.attempts >= MAX_ATTEMPTS:
        row.status, row.last_error = "failed", "已达到自动发送次数上限"
        await db.commit()
        return
    if row.category == "support" and row.created_at < now - timedelta(days=1):
        row.status, row.last_error = "skipped", "通知已超过 24 小时，请在站内查看最新状态"
        await db.commit()
        return
    if row.category == "support":
        previous_sent = await db.scalar(select(func.max(NotificationDelivery.sent_at)).where(
            NotificationDelivery.topic == row.topic, NotificationDelivery.recipient == row.recipient,
            NotificationDelivery.gateway_key == row.gateway_key, NotificationDelivery.status == "sent",
        ))
        if previous_sent and previous_sent + timedelta(seconds=60) > now:
            row.status, row.available_at = "pending", previous_sent + timedelta(seconds=60)
            await db.commit()
            return
    # Four-second spacing also stays below WeCom's per-member hourly cap.
    last_query = select(func.max(NotificationDelivery.last_attempt_at)).where(NotificationDelivery.gateway_key == row.gateway_key)
    if row.channel == "wecom":
        last_query = last_query.where(NotificationDelivery.recipient == row.recipient)
    last = await db.scalar(last_query)
    spacing = 4 if row.channel == "wecom" else max(0, int(await get_settings_store().get(db, "EMAIL_SEND_DELAY", 2)))
    if last and last + timedelta(seconds=spacing) > now:
        row.status, row.available_at = "pending", last + timedelta(seconds=spacing)
        await db.commit()
        return
    site = await get_settings_store().get(db, "SITE_URL", SETTINGS_SPECS["SITE_URL"].default_value())
    brand = await get_settings_store().get(db, "BRAND_NAME", SETTINGS_SPECS["BRAND_NAME"].default_value())
    site = str(site or "").rstrip("/")
    parsed = urlsplit(site)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.password:
        row.status, row.last_error = "failed", "请先在站点设置中配置有效的站点 URL"
        await db.commit()
        return
    row.status = "sending"
    row.attempts += 1
    row.last_attempt_at = now
    # A killed worker leaves a recoverable lease; the advisory lock excludes live peers.
    row.available_at = now + timedelta(minutes=2)
    await db.commit()
    try:
        if row.channel == "wecom":
            row.message_id = await wecom.client.send(
                settings, recipient=row.recipient, title=f"{brand} · {row.title}",
                body=f"站点：{parsed.netloc}\n{row.body}", url=site + "/#" + row.path, reference=row.id,
            )
        else:
            from app.services.email import EmailClient, get_smtp_config, load_template, render_template_body
            subject, body = row.title, row.body
            if row.context.get("template"):
                template = await load_template(db, row.context["template"])
                subject, body = render_template_body(template, {"brand_name": brand, **row.context.get("variables", {})})
            async with EmailClient(await get_smtp_config(db), site) as client:
                ok, error = await client.send(recipient_email=row.recipient, subject=subject,
                    main_content_raw=body, greeting="尊敬的管理员：", action_text="查看详情", action_url=site + "/#" + row.path)
            if not ok:
                raise wecom.DeliveryError(error or "邮件发送失败", retryable=True)
        row.status, row.sent_at, row.last_error = "sent", utc_naive_now(), None
        if row.category == "monitoring" and row.context.get("kind") == "fired":
            from app.db.models.monitoring import HostAlert
            alert = await db.get(HostAlert, row.context.get("alert_id"))
            if alert:
                alert.notified, alert.last_notified_at = True, row.sent_at
    except (wecom.DeliveryError, ValueError) as exc:
        row.last_error = str(exc)[:500]
        retryable = isinstance(exc, wecom.DeliveryError) and exc.retryable
        row.status = "pending" if retryable and row.attempts < MAX_ATTEMPTS else "failed"
        row.available_at = utc_naive_now() + timedelta(seconds=min(1800, 30 * 2 ** min(row.attempts - 1, 6)))
    await db.commit()


async def run_notifications() -> None:
    # GET_LOCK is connection-scoped: pin the connection across commits and HTTP calls.
    async with get_engine().connect() as connection:
        lock_name = "manager_notifications_dispatch"
        acquired = await connection.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": lock_name})
        await connection.commit()
        if acquired != 1:
            return
        try:
            async with AsyncSession(bind=connection, expire_on_commit=False, autoflush=False) as db:
                ids = list((await db.scalars(select(NotificationDelivery.id).where(
                    NotificationDelivery.status.in_(("pending", "sending")),
                    NotificationDelivery.available_at <= utc_naive_now(),
                ).order_by(case((NotificationDelivery.severity == "critical", 0), (NotificationDelivery.severity == "warning", 1), else_=2), NotificationDelivery.id).limit(30))).all())
                await db.commit()
                for row_id in ids:
                    try:
                        await _dispatch(db, row_id)
                    except Exception as exc:
                        await db.rollback()
                        logger.error("notification dispatch failed id=%s error_type=%s", row_id, type(exc).__name__)
                        failed = await db.get(NotificationDelivery, row_id)
                        if failed is not None and failed.status in {"pending", "sending"}:
                            failed.status, failed.last_error = "failed", f"发送处理异常（{type(exc).__name__}）"
                            await db.commit()
                    db.expunge_all()
        finally:
            await connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
            await connection.commit()
