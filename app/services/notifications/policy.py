"""Shared notification routing and monitoring defaults."""

from typing import Any, Literal
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import alert_defaults
from app.core.runtime_settings import AUTOMATION_SPECS, CERTIFICATE_SPECS, defaults_for
from app.core.settings_store import get_settings_store

CATEGORIES = ("support", "monitoring", "certificate", "billing", "system")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecipientGroup(StrictModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=60)
    all_admins: bool = False
    admin_ids: list[int] = Field(default_factory=list, max_length=200)
    wecom_ids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_members(self) -> "RecipientGroup":
        from app.services.notifications.wecom import normalize_recipients
        normalized = normalize_recipients(self.wecom_ids)
        if any(not re.fullmatch(r"[a-z0-9_.@-]{1,64}", member) or member == "@all" for member in normalized) or any(i < 1 for i in self.admin_ids):
            raise ValueError("接收人格式不正确")
        self.wecom_ids = normalized
        return self


class RouteRule(StrictModel):
    email: bool = False
    wecom: bool = True
    email_group: str = "default"
    wecom_group: str = "default"
    min_severity: Literal["info", "warning", "critical"] = "warning"
    email_resolved: bool = False
    wecom_resolved: bool = True
    cooldown_min: int = Field(default=30, ge=1, le=1440)


class MetricRule(StrictModel):
    enabled: bool = True
    threshold: float | None = Field(default=None, ge=0, le=100)
    warning_threshold: float | None = Field(default=None, ge=0, le=100)
    critical_threshold: float | None = Field(default=None, ge=0, le=100)
    sustain_min: int | None = Field(default=None, ge=1, le=60)

    @model_validator(mode="after")
    def thresholds(self) -> "MetricRule":
        if self.warning_threshold is not None and self.critical_threshold is not None and self.warning_threshold >= self.critical_threshold:
            raise ValueError("严重阈值必须大于警告阈值")
        return self


class LifecycleRule(StrictModel):
    expiry: bool = False
    expired: bool = False
    pre_delete: bool = False
    installed: bool = False


class NotificationPolicy(StrictModel):
    groups: list[RecipientGroup] = Field(min_length=1, max_length=30)
    routes: dict[str, RouteRule]
    monitoring: dict[str, MetricRule]
    lifecycle: LifecycleRule

    @model_validator(mode="before")
    @classmethod
    def disk_fields(cls, value: Any) -> Any:
        if isinstance(value, dict) and isinstance(value.get("monitoring"), dict):
            value = {**value, "monitoring": {k: (dict(v) if isinstance(v, dict) else v) for k, v in value["monitoring"].items()}}
            for key, unused in (("disk_high", "critical_threshold"), ("disk_critical", "warning_threshold")):
                rule = value["monitoring"].get(key)
                if isinstance(rule, dict):
                    rule.pop(unused, None)
        return value

    @model_validator(mode="after")
    def references(self) -> "NotificationPolicy":
        ids = {g.id for g in self.groups}
        if len(ids) != len(self.groups) or set(self.routes) != set(CATEGORIES):
            raise ValueError("接收组重复或通知类型不完整")
        if set(self.monitoring) != set(alert_defaults.ALERT_TYPES) - {"cert_source_expiring"}:
            raise ValueError("监控规则不完整")
        for rule in self.routes.values():
            if rule.email_group not in ids or rule.wecom_group not in ids:
                raise ValueError("通知规则引用了不存在的接收组")
        warning = self.monitoring["disk_high"].warning_threshold
        critical = self.monitoring["disk_critical"].critical_threshold
        if warning is not None and critical is not None and warning >= critical:
            raise ValueError("磁盘严重阈值必须大于警告阈值")
        return self


async def load_policy(db: AsyncSession) -> NotificationPolicy:
    store = get_settings_store()
    saved = await store.get(db, "NOTIFICATION_POLICY", None)
    if saved is not None:
        return NotificationPolicy.model_validate(saved)
    old = await store.get_many(db, defaults_for({**CERTIFICATE_SPECS, **AUTOMATION_SPECS}))
    def ids(raw: Any) -> list[int]:
        return [int(x) for x in str(raw or "").split(",") if x.strip().isdigit()]
    monitor_ids = ids(await store.get(db, "ALERT_DEFAULT_RECIPIENTS", ""))
    cert_ids = ids(old["CERT_ALERT_EMAIL_ADMIN_IDS"])
    groups = [
        RecipientGroup(id="default", name="默认接收组", all_admins=True),
        RecipientGroup(id="monitoring", name="主机告警", all_admins=not monitor_ids, admin_ids=monitor_ids),
        RecipientGroup(id="certificate", name="证书告警", all_admins=not cert_ids, admin_ids=cert_ids),
    ]
    routes = {key: RouteRule() for key in CATEGORIES}
    routes["support"].min_severity = "info"
    routes["monitoring"].email = True
    routes["monitoring"].email_group = "monitoring"
    routes["certificate"].email = bool(old["CERT_ALERT_EMAIL_ENABLED"])
    routes["certificate"].email_group = "certificate"
    routes["billing"].email = True
    active = bool(old["AUTOMATION_EMAIL_ENABLED"])
    return NotificationPolicy(groups=groups, routes=routes,
        monitoring={k: MetricRule.model_validate(alert_defaults.default_rule(k)) for k in alert_defaults.ALERT_TYPES if k != "cert_source_expiring"},
        lifecycle=LifecycleRule(expiry=active, expired=active, pre_delete=active, installed=active))


async def monitoring_defaults(db: AsyncSession) -> dict[str, Any]:
    policy = await load_policy(db)
    rule = policy.routes["monitoring"]
    group = next(g for g in policy.groups if g.id == rule.email_group)
    return {
        "email_enabled": rule.email, "email_recipients": [] if group.all_admins else group.admin_ids,
        "min_severity": rule.min_severity, "notify_resolve": rule.email_resolved,
        "cooldown_min": rule.cooldown_min,
        "agent_pull_timeout": alert_defaults.DEFAULT_AGENT_PULL_TIMEOUT,
        "agent_pull_attempts": alert_defaults.DEFAULT_AGENT_PULL_ATTEMPTS,
        "rules": {k: r.model_dump(exclude_none=True) for k, r in policy.monitoring.items()},
    }
