"""Email service — async SMTP sending and template management for FastAPI."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import secrets
import smtplib
import string
from dataclasses import dataclass
from datetime import datetime
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from typing import Any

import jinja2
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime_settings import SETTINGS_SPECS
from app.core.settings_store import get_settings_store
from app.db.models.manager import ManagerEmailTemplate

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_TEMPLATES_DIR = _PROJECT_ROOT / "app" / "templates"
_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=True,
)

_EMAIL_THEME_COLORS: dict[str, dict[str, str]] = {
    "light": {
        "page_bg": "#f4f6f5",
        "card_bg": "#ffffff",
        "border": "#e2e8e6",
        "text": "#1a2420",
        "muted": "#4a5c56",
        "subtle": "#8a9c96",
        "divider": "#e8ece9",
        "brand": "#0d9488",
        "button": "#14b8a6",
        "button_text": "#ffffff",
    },
    "dark": {
        "page_bg": "#0b0f0f",
        "card_bg": "#111818",
        "border": "#263434",
        "text": "#e4ece8",
        "muted": "#94a8a0",
        "subtle": "#5a706a",
        "divider": "#263434",
        "brand": "#2dd4bf",
        "button": "#14b8a6",
        "button_text": "#ffffff",
    },
}
_jinja_env.globals["colors"] = _EMAIL_THEME_COLORS["light"]

_AUTOMATED_NOTICE = "此邮件由系统自动发送，请勿直接回复。"


# ── Utilities ──

def generate_temporary_password(length: int = 12) -> str:
    """Generate a random temporary password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c in string.ascii_lowercase for c in pwd)
                and any(c in string.ascii_uppercase for c in pwd)
                and any(c in string.digits for c in pwd)
                and any(c in "!@#$%" for c in pwd)):
            return pwd


# ── Template data ──

@dataclass
class EmailTemplate:
    subject: str
    body: str


# API name → internal template key mapping
EMAIL_TEMPLATE_API_TO_INTERNAL = {
    "bulk": "bulk",
    "reminder": "reminder",
    "pre_delete": "pre_delete",
    "create_user": "create_user",
    "password_reset": "password_reset",
    "email_change": "email_change",
    "preDelete": "pre_delete",
    "createUser": "create_user",
    "passwordReset": "password_reset",
    "emailChange": "email_change",
}

EMAIL_TEMPLATE_INTERNAL_KEYS = (
    "bulk",
    "reminder",
    "pre_delete",
    "create_user",
    "password_reset",
    "email_change",
)

_TEMPLATE_FILES = {
    "bulk": _PROJECT_ROOT / "templates" / "email_template.json",
    "reminder": _PROJECT_ROOT / "templates" / "reminder_template.json",
    "pre_delete": _PROJECT_ROOT / "templates" / "pre_delete_reminder_template.json",
    "create_user": _PROJECT_ROOT / "templates" / "create_user_template.json",
    "password_reset": _PROJECT_ROOT / "templates" / "password_reset_template.json",
    "email_change": _PROJECT_ROOT / "templates" / "email_change_template.json",
}

_PREVIEW_DUMMY_VALUES: dict[str, str] = {
    "username": "preview_user",
    "email": "preview@example.com",
    "server_name": "Paper Survival #1",
    "server_id": "12345",
    "expiration_date": "2026-04-30",
    "server_count": "2",
    "server_list": "- Paper Survival #1 (ID: 12345)\n- Velocity Proxy (ID: 12346)",
    "deletion_date": "2026-04-20",
    "password": "TempPass#123",
    "new_email": "new-preview@example.com",
}

_PREVIEW_ACTIONS: dict[str, tuple[str, str]] = {
    "bulk": ("登录系统查看", "/"),
    "reminder": ("登录系统处理", "/"),
    "pre_delete": ("登录系统处理", "/"),
    "create_user": ("设置您的账户密码", "/#/reset-password?token=preview-token&email=preview@example.com"),
    "password_reset": ("重置密码", "/#/reset-password?token=preview-token&email=preview@example.com"),
    "email_change": ("确认更改", "/#/confirm-email?token=preview-token&uid=10001"),
}


# ── Template CRUD ──

def _load_template_from_file(template_type: str) -> EmailTemplate:
    filepath = _TEMPLATE_FILES.get(template_type)
    if not filepath:
        return EmailTemplate(subject="", body="")
    try:
        with filepath.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return EmailTemplate(subject=data.get("subject", ""), body=data.get("body", ""))
    except FileNotFoundError:
        logger.error("Email template fallback file is missing: %s", filepath)
        return EmailTemplate(subject="", body="")
    except json.JSONDecodeError:
        logger.exception("Email template fallback file is invalid JSON: %s", filepath)
        return EmailTemplate(subject="", body="")


async def load_template(db: AsyncSession, template_type: str) -> EmailTemplate:
    """Load an email template from DB, with repository JSON fallback."""
    if template_type not in EMAIL_TEMPLATE_INTERNAL_KEYS:
        return EmailTemplate(subject="", body="")

    record = await db.get(ManagerEmailTemplate, template_type)
    if record is not None:
        return EmailTemplate(subject=record.subject, body=record.body)

    return _load_template_from_file(template_type)


async def save_template(
    db: AsyncSession,
    template_type: str,
    *,
    subject: str,
    body: str,
) -> None:
    """Save an email template by type to DB."""
    if template_type not in EMAIL_TEMPLATE_INTERNAL_KEYS:
        return

    record = await db.get(ManagerEmailTemplate, template_type)
    if record is None:
        db.add(ManagerEmailTemplate(
            template_key=template_type,
            subject=subject,
            body=body,
        ))
        return

    record.subject = subject
    record.body = body


async def load_all_templates(db: AsyncSession) -> dict[str, EmailTemplate]:
    """Load all template types."""
    return {t: await load_template(db, t) for t in EMAIL_TEMPLATE_INTERNAL_KEYS}


# ── Template rendering ──

def render_template_body(
    template: EmailTemplate,
    variables: dict[str, Any],
) -> tuple[str, str]:
    """Apply {{key}} placeholder substitution on subject and body.

    Values are HTML-escaped to prevent injection in email content.
    Returns (rendered_subject, rendered_body).
    """
    subject = template.subject
    body = template.body
    for key, value in variables.items():
        safe_value = html.escape(str(value))
        placeholder = "{{" + key + "}}"
        subject = subject.replace(placeholder, safe_value)
        body = body.replace(placeholder, safe_value)
    return subject, body


def render_email_shell(
    *,
    panel_name: str,
    panel_url: str,
    greeting: str,
    main_content_raw: str,
    action_text: str | None = None,
    action_url: str | None = None,
    theme: str = "light",
) -> str:
    main_content_html = main_content_raw.replace("\n", "<br>")
    template = _jinja_env.get_template("email_base.html")
    colors = _EMAIL_THEME_COLORS["dark" if theme == "dark" else "light"]
    return template.render(
        panel_name=panel_name,
        panel_url=panel_url,
        greeting=greeting,
        main_content=main_content_html,
        action_text=action_text,
        action_url=action_url,
        automated_notice=_AUTOMATED_NOTICE,
        current_year=datetime.now().year,
        colors=colors,
    )


# ── SMTP helpers ──

async def _get_smtp_config(db: AsyncSession) -> dict[str, Any]:
    """Read SMTP settings from runtime settings store."""
    store = get_settings_store()
    keys = {
        "SMTP_HOST": SETTINGS_SPECS["SMTP_HOST"].default_value(),
        "SMTP_PORT": SETTINGS_SPECS["SMTP_PORT"].default_value(),
        "SMTP_USE_SSL": SETTINGS_SPECS["SMTP_USE_SSL"].default_value(),
        "SMTP_PASSWORD": SETTINGS_SPECS["SMTP_PASSWORD"].default_value(),
        "SENDER_EMAIL": SETTINGS_SPECS["SENDER_EMAIL"].default_value(),
        "BRAND_NAME": SETTINGS_SPECS["BRAND_NAME"].default_value(),
    }
    return await store.get_many(db, keys)


async def get_email_delay(db: AsyncSession) -> int:
    """Get the inter-email delay in seconds from runtime settings."""
    store = get_settings_store()
    val = await store.get(db, "EMAIL_SEND_DELAY", SETTINGS_SPECS["EMAIL_SEND_DELAY"].default_value())
    return int(val)


async def get_site_url(db: AsyncSession) -> str:
    """Return the public manager URL used in email links and branding."""
    store = get_settings_store()
    url = str(await store.get(db, "SITE_URL", "")).rstrip("/")
    if url:
        return url

    from app.core.config import get_settings
    return (get_settings().ptero_panel_url or "").rstrip("/")


async def build_template_preview(
    db: AsyncSession,
    *,
    template_type: str,
    subject: str,
    body: str,
    theme: str = "light",
) -> tuple[str, str]:
    """Render a full preview document for an email template draft."""
    internal_key = EMAIL_TEMPLATE_API_TO_INTERNAL[template_type]
    store = get_settings_store()
    brand_name = str(await store.get(db, "BRAND_NAME", SETTINGS_SPECS["BRAND_NAME"].default_value()))
    site_url = await get_site_url(db)

    variables = {
        "brand_name": brand_name,
        **_PREVIEW_DUMMY_VALUES,
        "reset_url": f"{site_url}/#/reset-password?token=preview-token&email=preview@example.com",
        "confirm_url": f"{site_url}/#/confirm-email?token=preview-token&uid=10001",
    }
    rendered_subject, rendered_body = render_template_body(
        EmailTemplate(subject=subject, body=body),
        variables,
    )

    action_text, action_path = _PREVIEW_ACTIONS[internal_key]
    action_url = f"{site_url}{action_path}" if action_path.startswith("/") else action_path
    html_body = render_email_shell(
        panel_name=brand_name,
        panel_url=site_url,
        greeting="您好，preview_user！",
        main_content_raw=rendered_body,
        action_text=action_text,
        action_url=action_url,
        theme=theme,
    )
    return rendered_subject, html_body


# ── Send ──

async def send_email(
    db: AsyncSession,
    *,
    recipient_email: str,
    subject: str,
    main_content_raw: str,
    greeting: str,
    action_text: str | None = None,
    action_url: str | None = None,
) -> tuple[bool, str | None]:
    """Send an HTML email via SMTP.

    Returns (success, error_message_or_none).
    """
    cfg = await _get_smtp_config(db)
    sender_email = str(cfg.get("SENDER_EMAIL", ""))
    smtp_host = str(cfg.get("SMTP_HOST", ""))
    smtp_port = int(cfg.get("SMTP_PORT", 587))
    smtp_password = str(cfg.get("SMTP_PASSWORD", ""))
    smtp_use_ssl = bool(cfg.get("SMTP_USE_SSL", True))
    brand_name = str(cfg.get("BRAND_NAME", "Ptero Manager"))

    if not all([smtp_host, smtp_port, smtp_password, sender_email]):
        msg = "SMTP 配置不完整（主机、端口、密码、发件人地址），请检查系统设置。"
        logger.error(msg)
        return False, msg

    site_url = await get_site_url(db)
    html_body = render_email_shell(
        panel_name=brand_name,
        panel_url=site_url,
        greeting=greeting,
        main_content_raw=main_content_raw,
        action_text=action_text,
        action_url=action_url,
    )

    mime = MIMEText(html_body, "html", "utf-8")
    mime["From"] = formataddr((Header(brand_name, "utf-8").encode(), sender_email))
    mime["To"] = recipient_email
    mime["Subject"] = Header(subject, "utf-8")

    try:
        server_class = smtplib.SMTP_SSL if smtp_use_ssl else smtplib.SMTP
        raw_msg = mime.as_string()

        def _do_send() -> None:
            with server_class(smtp_host, smtp_port, timeout=20) as server:
                if not smtp_use_ssl:
                    server.starttls()
                server.login(sender_email, smtp_password)
                server.sendmail(sender_email, [recipient_email], raw_msg)

        await asyncio.to_thread(_do_send)
        logger.info("邮件已成功发送至 %s", recipient_email)
        return True, None
    except Exception as exc:
        logger.error("邮件发送失败 to %s: %s", recipient_email, exc, exc_info=True)
        return False, str(exc)
