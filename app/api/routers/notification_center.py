"""Unified notification configuration and current alerts."""

import hashlib
import json
import re
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.rate_limit import limiter
from app.core.runtime_settings import AUTOMATION_SPECS, NOTIFICATION_SPECS, SETTINGS_SPECS, defaults_for
from app.core.settings_store import get_settings_store
from app.core.time import utc_naive_now
from app.db.models.manager import ManagerCertificate, ManagerHost
from app.db.models.monitoring import HostAlert
from app.db.models.notifications import NotificationDelivery, NotificationIssue
from app.db.models.pterodactyl import PteroUser
from app.services.audit import log_manager_activity
from app.services.notifications.center import current_problems
from app.services.notifications.policy import NotificationPolicy, load_policy
from app.services.notifications import wecom

router = APIRouter(prefix="/admin/notifications", tags=["notifications"])
KEYS = {"WECOM_ENABLED", "WECOM_CORP_ID", "WECOM_AGENT_ID", "WECOM_SECRET", "NOTIFY_SUPPORT_DELAY",
        "SMTP_HOST", "SMTP_PORT", "SMTP_USE_SSL", "SMTP_PASSWORD", "SENDER_EMAIL", "EMAIL_SEND_DELAY",
        "AUTOMATION_EMAIL_RUN_HOUR", "AUTOMATION_EMAIL_RUN_MINUTE", "TIMEZONE"}
SPECS = {k: v for k, v in {**NOTIFICATION_SPECS, **SETTINGS_SPECS, **AUTOMATION_SPECS}.items() if k in KEYS}


@router.get("/center")
async def get_center(_: PteroUser = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    get_settings_store().clear()
    values = await get_settings_store().get_many(db, defaults_for(SPECS))
    policy = (await load_policy(db)).model_dump()
    certificates = [{"id": c.id, "name": c.name, "days": c.alert_threshold_days} for c in (await db.scalars(select(ManagerCertificate).order_by(ManagerCertificate.id))).all()]
    revision = hashlib.sha256(json.dumps([values, policy, certificates], sort_keys=True).encode()).hexdigest()
    admins = [{"value": u.id, "label": f"{u.username} · {u.email}"} for u in (await db.scalars(select(PteroUser).where(PteroUser.root_admin.is_(True)))).all()]
    hosts = [{"id": h.id, "name": h.name, "kind": h.kind} for h in (await db.scalars(select(ManagerHost).order_by(ManagerHost.id))).all()]
    return {"settings": values, "policy": policy, "certificates": certificates, "revision": revision, "admins": admins, "hosts": hosts}


class CenterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str
    settings: dict[str, Any] = Field(default_factory=dict)
    policy: NotificationPolicy | None = None
    certificates: dict[int, int] = Field(default_factory=dict)


@router.put("/center")
async def save_center(body: CenterInput, admin: PteroUser = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    store = get_settings_store()
    store.clear()
    current = await get_center(admin, db)
    if body.revision != current["revision"]:
        raise HTTPException(409, "设置已在其他页面修改，请重新加载")
    changes = {}
    for key, value in body.settings.items():
        if key not in SPECS or isinstance(value, (dict, list)) or (isinstance(value, str) and len(value) > 8000):
            raise HTTPException(400, "配置格式不正确")
        spec = SPECS[key]
        try:
            changes[key] = spec.normalize(value)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    values = await store.get_many(db, defaults_for(SPECS))
    values.update(changes)
    policy = body.policy or await load_policy(db)
    admin_ids = {a["value"] for a in current["admins"]}
    if any(not set(g.admin_ids) <= admin_ids for g in policy.groups):
        raise HTTPException(400, "接收组包含不存在的管理员")
    if values["WECOM_ENABLED"]:
        members = list(dict.fromkeys(x for group in policy.groups for x in group.wecom_ids))
        try:
            wecom.validate(values, members)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    if values["SENDER_EMAIL"] and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", values["SENDER_EMAIL"]):
        raise HTTPException(400, "发件邮箱格式不正确")
    for cert_id, days in body.certificates.items():
        cert = await db.get(ManagerCertificate, cert_id)
        if cert is None or not 1 <= days <= 90:
            raise HTTPException(400, "证书或提前提醒天数不正确")
        cert.alert_threshold_days = days
    if body.policy:
        changes["NOTIFICATION_POLICY"] = policy.model_dump()
    await store.set_values(db, changes, category="notifications", commit=False)
    await db.commit()
    await log_manager_activity(db, actor=admin.username, category="settings", status="success", detail_key="settings_change",
        detail_params={"actor": admin.username, "keys": sorted(changes)})
    return await get_center(admin, db)


class TestInput(BaseModel):
    group: str = Field(max_length=40)


@router.post("/center/test")
@limiter.limit("5/minute")
async def test_channel(request: Request, body: TestInput, _: PteroUser = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    values = await get_settings_store().get_many(db, defaults_for(NOTIFICATION_SPECS))
    group = next((g for g in (await load_policy(db)).groups if g.id == body.group), None)
    if not values["WECOM_ENABLED"] or not group or not group.wecom_ids:
        raise HTTPException(400, "请启用企业微信并选择包含成员账号的接收组")
    site = str(await get_settings_store().get(db, "SITE_URL", "")).rstrip("/")
    try:
        wecom.validate(values, group.wecom_ids)
        for member in group.wecom_ids:
            await wecom.client.send(values, recipient=member, title="通知渠道测试", body="企业微信连接成功。",
                url=site + "/#/admin/notifications?tab=channels", reference=int(utc_naive_now().timestamp()))
    except (ValueError, wecom.DeliveryError) as exc:
        raise HTTPException(400, str(exc)) from None
    return {"ok": True}


@router.get("/alerts")
async def get_alerts(category: Literal["all", "monitoring", "certificate", "billing", "system"] = "all",
    state: Literal["all", "open", "acknowledged", "muted"] = "all", q: str = Query("", max_length=200),
    offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
    _: PteroUser = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    items = await current_problems(db)
    counts = {key: sum(item["state"] == key for item in items) for key in ("open", "acknowledged", "muted")}
    filtered = [item for item in items if (category == "all" or item["category"] == category)
        and (state == "all" or item["state"] == state)
        and (not q or q.casefold() in f"{item['title']} {item['body']}".casefold())]
    return {"items": filtered[offset:offset + limit], "total": len(filtered), "counts": counts, "has_more": offset + limit < len(filtered)}


class AlertAction(BaseModel):
    key: str = Field(max_length=190)
    action: Literal["acknowledge", "mute", "unmute", "close"]
    minutes: int = Field(default=60, ge=1, le=10080)


@router.post("/alerts/action")
async def alert_action(body: AlertAction, admin: PteroUser = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    item = next((x for x in await current_problems(db) if x["key"] == body.key), None)
    if item is None:
        raise HTTPException(404, "告警已恢复或不存在")
    if body.action == "close" and item["category"] != "system":
        raise HTTPException(400, "请在对应业务页面处理问题")
    now = utc_naive_now()
    row: HostAlert | NotificationIssue | None
    if item["category"] == "monitoring":
        row = await db.get(HostAlert, int(body.key.split(":")[1]))
    else:
        row = await db.get(NotificationIssue, body.key)
        if row is None:
            row = NotificationIssue(key=body.key, category=item["category"], severity=item["severity"], title=item["title"], body=item["body"], path=item["path"])
            db.add(row)
    if row is None:
        raise HTTPException(404, "告警不存在")
    if body.action == "acknowledge":
        row.acknowledged_at = now
    elif body.action == "mute":
        row.muted_until = now + timedelta(minutes=body.minutes)
    elif body.action == "unmute":
        row.muted_until = None
        context = NotificationDelivery.context
        if item["category"] == "monitoring":
            pending_issue = (context["alert_id"].as_integer() == int(body.key.split(":")[1])) & (context["kind"].as_string() == "fired")
        elif item["category"] == "billing":
            pending_issue = context["incident_id"].as_integer() == int(body.key.split(":")[1])
        else:
            pending_issue = context["problem_key" if item["category"] == "certificate" else "issue_key"].as_string() == body.key
        await db.execute(update(NotificationDelivery).where(
            NotificationDelivery.status == "pending", NotificationDelivery.last_error == "告警已临时静默",
            pending_issue,
        ).values(available_at=now, last_error=None))
    else:
        row.resolved_at = now
    await db.commit()
    await log_manager_activity(db, actor=admin.username, category="monitoring", status="success",
        detail_key="notification.alert.action", detail_params={"key": body.key, "action": body.action})
    return {"ok": True}
