"""Editable plain-text WeCom templates shared by preview and delivery."""

import html
import re
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime_settings import SETTINGS_SPECS
from app.core.settings_store import get_settings_store
from app.db.models.notifications import NotificationDelivery
from app.services.notifications.wecom import format_content

TemplateKey = Literal[
    "support", "alert_fired", "alert_resolved", "certificate",
    "billing_incident", "billing_apply", "audit_failure", "task_failure",
]


class WecomTemplate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(max_length=8000)


class TemplateInput(WecomTemplate):
    type: TemplateKey


COMMON_VARIABLES = ("brand_name", "site_name", "notification_id", "severity_label")
VARIABLES: dict[TemplateKey, tuple[str, ...]] = {
    "support": ("username", "message_count", "messages"),
    "alert_fired": ("node_name", "node_id", "alert_type_label", "alert_message", "fired_at"),
    "alert_resolved": ("node_name", "node_id", "alert_type_label", "alert_message", "fired_at", "resolved_at"),
    "certificate": ("certificate_id", "certificate_name", "alert_type_label", "expires_at", "target", "error"),
    "billing_incident": ("incident_id", "incident_type_label", "order_id", "server_id"),
    "billing_apply": ("order_no", "username", "plan_name", "total_yuan", "currency_code", "apply_retry_count", "apply_error"),
    "audit_failure": ("actor", "operation", "status_label", "target"),
    "task_failure": ("job_id", "error_type"),
}
DEFAULT = WecomTemplate(title="{{brand_name}} · {{title}}", body="站点：{{site_name}}\n通知编号：{{notification_id}}\n{{message}}")
DEFAULTS: dict[TemplateKey, WecomTemplate] = {
    "support": WecomTemplate(title="{{brand_name}} · 客服新消息",
        body="站点：{{site_name}}\n通知编号：{{notification_id}}\n用户：{{username}}\n未读消息：{{message_count}} 条\n消息摘要：\n{{messages}}\n\n请进入客服页面回复。"),
    "alert_fired": WecomTemplate(title="{{brand_name}} · 监控告警",
        body="站点：{{site_name}}\n通知编号：{{notification_id}}\n主机：{{node_name}}\n告警类型：{{alert_type_label}}\n告警等级：{{severity_label}}\n触发时间：{{fired_at}}\n监测记录：{{alert_message}}\n\n请检查主机状态，并处理异常。"),
    "alert_resolved": WecomTemplate(title="{{brand_name}} · 监控恢复",
        body="站点：{{site_name}}\n通知编号：{{notification_id}}\n主机：{{node_name}}\n告警类型：{{alert_type_label}}\n触发时间：{{fired_at}}\n恢复时间：{{resolved_at}}\n\n告警已恢复，请确认相关服务运行正常。"),
    "certificate": WecomTemplate(title="{{brand_name}} · 证书异常",
        body="站点：{{site_name}}\n通知编号：{{notification_id}}\n证书：{{certificate_name}}\n告警类型：{{alert_type_label}}\n告警等级：{{severity_label}}\n到期时间：{{expires_at}}\n部署目标：{{target}}\n错误记录：{{error}}\n\n请检查证书有效期、源文件及部署状态，并处理异常。"),
    "billing_incident": WecomTemplate(title="{{brand_name}} · 订单与支付异常",
        body="站点：{{site_name}}\n通知编号：{{notification_id}}\n异常类型：{{incident_type_label}}\n异常记录：{{incident_id}}\n订单 ID：{{order_id}}\n服务器 ID：{{server_id}}\n\n请检查订单、支付及退款状态，并处理异常。"),
    "billing_apply": WecomTemplate(title="{{brand_name}} · 订单开通异常",
        body="站点：{{site_name}}\n通知编号：{{notification_id}}\n订单号：{{order_no}}\n用户：{{username}}\n套餐：{{plan_name}}\n重试次数：{{apply_retry_count}}\n错误记录：{{apply_error}}\n\n请检查订单开通状态，并处理异常。"),
    "audit_failure": WecomTemplate(title="{{brand_name}} · 操作异常",
        body="站点：{{site_name}}\n通知编号：{{notification_id}}\n操作类型：{{operation}}\n操作人：{{actor}}\n操作结果：{{status_label}}\n关联对象：{{target}}\n\n请检查活动日志，并处理异常。"),
    "task_failure": WecomTemplate(title="{{brand_name}} · 任务异常",
        body="站点：{{site_name}}\n通知编号：{{notification_id}}\n任务：{{job_id}}\n异常类型：{{error_type}}\n\n请检查运行日志，并处理异常。"),
}
TOKEN = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)


def setting_key(key: TemplateKey) -> str:
    return f"WECOM_TEMPLATE_{key.upper()}"


def validate_template(payload: TemplateInput) -> None:
    allowed = {*COMMON_VARIABLES, *VARIABLES[payload.type]}
    for text in (payload.title, payload.body):
        for token in TOKEN.findall(text):
            if token.strip() not in allowed:
                raise ValueError(f"不支持的模板变量：{token.strip()}")
        remaining = TOKEN.sub("", text)
        if "{{" in remaining or "}}" in remaining:
            raise ValueError("模板变量请使用 {{变量名}} 格式")


async def load_templates(db: AsyncSession) -> dict[TemplateKey, WecomTemplate]:
    values = await get_settings_store().get_many(db, {setting_key(key): value.model_dump() for key, value in DEFAULTS.items()})
    return {key: WecomTemplate.model_validate(values[setting_key(key)]) for key in VARIABLES}


def render(template: WecomTemplate, variables: dict[str, Any], *, url: str) -> str:
    def substitute(text: str) -> str:
        return TOKEN.sub(lambda match: str(variables.get(match[1].strip(), "")), text)
    return format_content(title=substitute(template.title), body=substitute(template.body), url=url)


async def delivery_content(db: AsyncSession, row: NotificationDelivery, *, brand: str, site: str) -> str:
    if "wecom_content" in row.context:
        return row.context["wecom_content"]
    from app.services.email import severity_label

    key = row.context.get("wecom_template")
    template = (await load_templates(db))[key] if key in VARIABLES else DEFAULT
    variables = {
        **row.context.get("variables", {}), **row.context.get("wecom_variables", {}),
        "brand_name": brand, "site_name": urlsplit(site).netloc, "notification_id": row.id,
        "title": row.title, "message": row.body, "severity_label": severity_label(row.severity),
    }
    content = render(template, variables, url=site + "/#" + row.path)
    # Persist the exact payload before sending; retries must keep WeCom's deduplication identity.
    row.context = {**row.context, "wecom_content": content}
    return content


SAMPLES: dict[TemplateKey, dict[str, str]] = {
    "support": {"username": "example", "message_count": "2", "messages": "请问如何续费？\n这是订单截图 [截图]"},
    "alert_fired": {"node_name": "示例主机", "node_id": "1", "alert_type_label": "CPU 使用率过高",
        "alert_message": "CPU 使用率持续超过 90%。", "fired_at": "2026-10-15T09:00:00Z"},
    "alert_resolved": {"node_name": "示例主机", "node_id": "1", "alert_type_label": "CPU 使用率过高",
        "alert_message": "CPU 使用率持续超过 90%。", "fired_at": "2026-10-15T09:00:00Z", "resolved_at": "2026-10-15T09:10:00Z"},
    "certificate": {"certificate_id": "1", "certificate_name": "示例证书", "alert_type_label": "证书即将到期",
        "expires_at": "2026-10-22T09:00:00Z", "target": "—", "error": "—"},
    "billing_incident": {"incident_id": "12", "incident_type_label": "订单需要人工审核", "order_id": "100", "server_id": "3"},
    "billing_apply": {"order_no": "EXAMPLE100", "username": "example", "plan_name": "SillyTavern 月付套餐",
        "total_yuan": "10.00", "currency_code": "CNY", "apply_retry_count": "2", "apply_error": "节点暂时不可用"},
    "audit_failure": {"actor": "admin", "operation": "服务器操作", "status_label": "失败", "target": "3"},
    "task_failure": {"job_id": "monitoring", "error_type": "TimeoutError"},
}


async def preview(db: AsyncSession, payload: TemplateInput) -> str:
    settings = await get_settings_store().get_many(db, {key: SETTINGS_SPECS[key].default_value() for key in ("BRAND_NAME", "SITE_URL")})
    site = str(settings["SITE_URL"] or "https://example.com").rstrip("/")
    content = render(payload, {**SAMPLES[payload.type], "brand_name": settings["BRAND_NAME"],
        "site_name": urlsplit(site).netloc, "notification_id": 123, "severity_label": "警告"}, url=site + "/#/admin/notifications")
    return html.unescape(re.sub(r'<a href="[^"]*">查看详情</a>', "查看详情", content))
