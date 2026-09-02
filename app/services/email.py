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
from app.services.audit import log_manager_activity

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
    "register_verify": "register_verify",
    "alert_fired": "alert_fired",
    "alert_resolved": "alert_resolved",
    "order_paid": "order_paid",
    "order_apply_failed": "order_apply_failed",
    "order_apply_alert": "order_apply_alert",
    "order_refunded": "order_refunded",
    "server_installed": "server_installed",
    "preDelete": "pre_delete",
    "createUser": "create_user",
    "passwordReset": "password_reset",
    "emailChange": "email_change",
    "registerVerify": "register_verify",
    "alertFired": "alert_fired",
    "alertResolved": "alert_resolved",
    "orderPaid": "order_paid",
    "orderApplyFailed": "order_apply_failed",
    "orderApplyAlert": "order_apply_alert",
    "orderRefunded": "order_refunded",
    "serverInstalled": "server_installed",
    "referral_inviter_rewarded": "referral_inviter_rewarded",
    "referral_invitee_rewarded": "referral_invitee_rewarded",
    "referralInviterRewarded": "referral_inviter_rewarded",
    "referralInviteeRewarded": "referral_invitee_rewarded",
    "expired": "expired",
}

EMAIL_TEMPLATE_INTERNAL_KEYS = (
    "bulk",
    "reminder",
    "expired",
    "pre_delete",
    "create_user",
    "password_reset",
    "email_change",
    "register_verify",
    "alert_fired",
    "alert_resolved",
    "order_paid",
    "order_apply_failed",
    "order_apply_alert",
    "order_refunded",
    "server_installed",
    "referral_inviter_rewarded",
    "referral_invitee_rewarded",
)

_TEMPLATE_FILES = {
    "bulk": _PROJECT_ROOT / "templates" / "email_template.json",
    "reminder": _PROJECT_ROOT / "templates" / "reminder_template.json",
    "expired": _PROJECT_ROOT / "templates" / "expired_reminder_template.json",
    "pre_delete": _PROJECT_ROOT / "templates" / "pre_delete_reminder_template.json",
    "create_user": _PROJECT_ROOT / "templates" / "create_user_template.json",
    "password_reset": _PROJECT_ROOT / "templates" / "password_reset_template.json",
    "email_change": _PROJECT_ROOT / "templates" / "email_change_template.json",
    "register_verify": _PROJECT_ROOT / "templates" / "register_verify_template.json",
    "alert_fired": _PROJECT_ROOT / "templates" / "alert_fired_template.json",
    "alert_resolved": _PROJECT_ROOT / "templates" / "alert_resolved_template.json",
    "order_paid": _PROJECT_ROOT / "templates" / "order_paid_template.json",
    "order_apply_failed": _PROJECT_ROOT / "templates" / "order_apply_failed_template.json",
    "order_apply_alert": _PROJECT_ROOT / "templates" / "order_apply_alert_template.json",
    "order_refunded": _PROJECT_ROOT / "templates" / "order_refunded_template.json",
    "server_installed": _PROJECT_ROOT / "templates" / "server_installed_template.json",
    "referral_inviter_rewarded": _PROJECT_ROOT / "templates" / "referral_inviter_rewarded_template.json",
    "referral_invitee_rewarded": _PROJECT_ROOT / "templates" / "referral_invitee_rewarded_template.json",
}

_PREVIEW_DUMMY_VALUES: dict[str, str] = {
    "username": "preview_user",
    "email": "preview@example.com",
    "server_name": "Paper Survival #1",
    "server_id": "12345",
    "expiration_date": "2026-04-30",
    "grace_days": "7",
    "server_count": "2",
    "server_list": "- Paper Survival #1 (ID: 12345)\n- Velocity Proxy (ID: 12346)",
    "deletion_date": "2026-04-20",
    "password": "TempPass#123",
    "new_email": "new-preview@example.com",
    "node_name": "node1-prod",
    "node_id": "1",
    "alert_type": "cpu_high",
    "alert_type_label": "CPU 使用率过高",
    "severity": "warning",
    "severity_label": "警告",
    "message": "CPU 92.3% > 90% sustained",
    "fired_at": "2026-04-21 14:32:11 UTC",
    "resolved_at": "2026-04-21 14:48:55 UTC",
    # Billing preview values (BILLING_DESIGN.md §14)
    "order_no": "O20260430000123",
    "plan_name": "SillyTavern 高级型",
    "period_count": "3",
    "total_days": "90",
    "total_fen": "5970",
    "total_yuan": "59.70",
    "currency_code": "CNY",
    "paid_at": "2026-04-30 12:34:56 UTC",
    "applied_at": "2026-04-30 12:35:08 UTC",
    "server_uuid": "e6777f85-44e9-45f9-ace9-2c2099753e9c",
    "refund_amount_fen": "5970",
    "refund_amount_yuan": "59.70",
    "refund_reason": "用户申请退款",
    "refund_no": "R20260430000045",
    "refunded_at": "2026-05-01 09:00:00 UTC",
    "apply_error": "node has no available allocation",
    "apply_retry_count": "3",
    "installed_at": "2026-05-04 08:58:42 UTC",
    # Referral coupon preview values
    "invitee_username": "new_friend",
    "coupon_code": "WELCOME-AB12CD34",
    "coupon_name": "新人欢迎券",
    "discount_yuan": "10.00",
    "min_order_yuan": "30.00",
    "min_order_text": "订单满 ¥30.00 可用",
    "expires_at": "2026-06-30",
}

_PREVIEW_ACTIONS: dict[str, tuple[str, str]] = {
    "bulk": ("登录系统查看", "/"),
    "reminder": ("登录系统处理", "/"),
    "expired": ("登录系统处理", "/#/servers"),
    "pre_delete": ("登录系统处理", "/"),
    "create_user": ("设置您的账户密码", "/#/reset-password?token=preview-token&email=preview@example.com"),
    "password_reset": ("重置密码", "/#/reset-password?token=preview-token&email=preview@example.com"),
    "email_change": ("确认更改", "/#/confirm-email?token=preview-token&uid=10001"),
    "register_verify": ("验证邮箱并完成注册", "/#/verify-email?token=preview-token"),
    "alert_fired": ("查看监控面板", "/#/admin/dashboard"),
    "alert_resolved": ("查看监控面板", "/#/admin/dashboard"),
    "order_paid": ("查看服务器", "/#/servers"),
    "order_apply_failed": ("", ""),
    "order_apply_alert": ("查看订单", "/#/admin/billing/orders"),
    "order_refunded": ("查看订单", "/#/account"),
    "server_installed": ("进入控制台", "/#/servers/12345/console"),
    "referral_inviter_rewarded": ("查看我的优惠券", "/#/account"),
    "referral_invitee_rewarded": ("查看我的优惠券", "/#/account"),
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

    Values are HTML-escaped to prevent injection. Newlines inside multi-line
    variable values (e.g. ``server_list``) are converted to ``<br>`` so they
    render as actual line breaks in the resulting HTML email body. Subject
    lines must remain a single line by RFC, so newlines are stripped from
    the subject substitution path.
    """
    subject = template.subject
    body = template.body
    for key, value in variables.items():
        raw = str(value)
        # Subject: single-line, escape only.
        subject_value = html.escape(raw.replace("\n", " ").replace("\r", " "))
        # Body: escape, then convert real newlines into <br>.
        body_value = html.escape(raw).replace("\n", "<br>")
        placeholder = "{{" + key + "}}"
        subject = subject.replace(placeholder, subject_value)
        body = body.replace(placeholder, body_value)
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

async def get_smtp_config(db: AsyncSession) -> dict[str, Any]:
    """Read SMTP-related settings from the runtime settings store.

    Public so batch senders can resolve the config once and pass it into
    ``EmailClient`` themselves, avoiding a per-message store lookup.
    """
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


class SiteUrlNotConfiguredError(RuntimeError):
    """Raised when an email-link flow is invoked but SITE_URL is not set."""


async def get_site_url(db: AsyncSession) -> str:
    """Return the public manager URL used in email links and branding.

    Strict: SITE_URL must be configured (and start with http/https). Email
    flows are unusable without a clickable absolute URL, so we fail loudly
    rather than silently emitting broken relative links. The previous
    fallback to ``ptero_panel_url`` was removed when the project decoupled
    from the Pterodactyl Panel application API.
    """
    store = get_settings_store()
    url = str(await store.get(db, "SITE_URL", "")).strip().rstrip("/")
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        raise SiteUrlNotConfiguredError(
            "SITE_URL is not configured. Set it in Settings → Branding."
        )
    return url


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
    # Preview must work even if SITE_URL is not yet configured. Fall back to
    # a clearly-fake placeholder so admins can still see the layout while
    # filling out branding settings.
    try:
        site_url = await get_site_url(db)
    except SiteUrlNotConfiguredError:
        site_url = "https://example.invalid"

    variables = {
        "brand_name": brand_name,
        **_PREVIEW_DUMMY_VALUES,
        "reset_url": f"{site_url}/#/reset-password?token=preview-token&email=preview@example.com",
        "confirm_url": f"{site_url}/#/confirm-email?token=preview-token&uid=10001",
        "verify_url": f"{site_url}/#/verify-email?token=preview-token",
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

# Exceptions where a retry has any chance of helping. Auth and recipient
# rejection failures are *not* retried because re-sending will only repeat
# the same error and waste an SMTP round-trip.
_RETRYABLE_SMTP_EXC = (
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPConnectError,
    smtplib.SMTPHeloError,
    ConnectionError,
    TimeoutError,
    OSError,  # covers socket.gaierror, socket.timeout
)


def _build_smtp_server(
    *, host: str, port: int, use_ssl: bool, sender: str, password: str
) -> smtplib.SMTP:
    """Open and authenticate an SMTP connection. Blocking; call inside to_thread."""
    cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    server = cls(host, port, timeout=20)
    if not use_ssl:
        server.starttls()
    server.login(sender, password)
    return server


class EmailClient:
    """Reusable SMTP connection + per-message renderer.

    A single ``EmailClient`` opens one SMTP connection in ``__aenter__`` and
    keeps it alive for the duration of the ``async with`` block, so batch
    senders (reminders, bulk emails) avoid the connect/login round-trip on
    every recipient. If the connection drops mid-batch, the next ``send()``
    transparently reconnects.

    Each successful or failed delivery attempt is recorded via
    ``log_manager_activity`` when ``db`` is provided, giving operators a
    per-recipient audit trail.
    """

    def __init__(
        self,
        cfg: dict[str, Any],
        site_url: str,
        *,
        db: AsyncSession | None = None,
        actor: str = "system",
        log_category: str = "email",
        audit_source: str | None = None,
    ) -> None:
        self._brand_name = str(cfg.get("BRAND_NAME", "Erocraft Manager"))
        self._sender_email = str(cfg.get("SENDER_EMAIL", ""))
        self._smtp_password = str(cfg.get("SMTP_PASSWORD", ""))
        self._smtp_host = str(cfg.get("SMTP_HOST", ""))
        self._smtp_port = int(cfg.get("SMTP_PORT", 587))
        self._smtp_use_ssl = bool(cfg.get("SMTP_USE_SSL", True))
        self._configured = all([
            self._smtp_host, self._smtp_port,
            self._smtp_password, self._sender_email,
        ])
        self._site_url = site_url
        self._db = db
        self._actor = actor
        self._log_category = log_category
        self._audit_source = audit_source
        self._server: smtplib.SMTP | None = None

    # ── Connection management ──
    def _open(self) -> None:
        self._server = _build_smtp_server(
            host=self._smtp_host, port=self._smtp_port,
            use_ssl=self._smtp_use_ssl,
            sender=self._sender_email, password=self._smtp_password,
        )

    def _close(self) -> None:
        if self._server is not None:
            try:
                self._server.quit()
            except Exception:  # noqa: BLE001 - close is best-effort
                pass
            self._server = None

    async def __aenter__(self) -> "EmailClient":
        if self._configured:
            try:
                await asyncio.to_thread(self._open)
            except Exception as exc:  # noqa: BLE001
                # Don't fail the whole context — let individual send() calls
                # surface the real per-message error / retry. This keeps a
                # transient DNS hiccup from blowing up an entire batch job.
                logger.warning("SMTP 连接初始化失败，将在每封邮件尝试重新连接: %s", exc)
                self._server = None
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await asyncio.to_thread(self._close)

    # ── Sending ──
    async def send(
        self,
        *,
        recipient_email: str,
        subject: str,
        main_content_raw: str,
        greeting: str,
        action_text: str | None = None,
        action_url: str | None = None,
    ) -> tuple[bool, str | None]:
        if not self._configured:
            err = "SMTP 配置不完整（主机、端口、密码、发件人地址），请检查系统设置。"
            logger.error(err)
            await self._audit(recipient_email, subject, ok=False, err=err)
            return False, err

        html_body = render_email_shell(
            panel_name=self._brand_name,
            panel_url=self._site_url,
            greeting=greeting,
            main_content_raw=main_content_raw,
            action_text=action_text,
            action_url=action_url,
        )
        mime = MIMEText(html_body, "html", "utf-8")
        mime["From"] = formataddr((Header(self._brand_name, "utf-8").encode(), self._sender_email))
        mime["To"] = recipient_email
        mime["Subject"] = str(Header(subject, "utf-8"))
        raw_msg = mime.as_string()

        # Up to 3 attempts: initial + 2 retries with exponential backoff.
        # Retryable failures close the connection so the next attempt
        # rebuilds it cleanly; this also recovers from a server that
        # silently closed an idle connection between batch messages.
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                if self._server is None:
                    await asyncio.to_thread(self._open)
                assert self._server is not None
                await asyncio.to_thread(
                    self._server.sendmail,
                    self._sender_email, [recipient_email], raw_msg,
                )
                if attempt > 0:
                    logger.info("邮件在第 %d 次尝试后发送成功 to %s", attempt + 1, recipient_email)
                else:
                    logger.info("邮件已成功发送至 %s", recipient_email)
                await self._audit(recipient_email, subject, ok=True, err=None)
                return True, None
            except _RETRYABLE_SMTP_EXC as exc:
                last_err = exc
                # Connection might be broken — close so the next iteration
                # rebuilds it. Best-effort close: ignore close errors.
                await asyncio.to_thread(self._close)
                if attempt < 2:
                    backoff = 2 ** attempt  # 1s, 2s
                    logger.warning(
                        "邮件发送失败 (可重试) to %s, 第 %d 次将在 %ds 后重试: %s",
                        recipient_email, attempt + 2, backoff, exc,
                    )
                    await asyncio.sleep(backoff)
                    continue
                logger.error("邮件发送失败 (重试已用尽) to %s: %s", recipient_email, exc, exc_info=True)
                await self._audit(recipient_email, subject, ok=False, err=str(exc))
                return False, str(exc)
            except Exception as exc:  # noqa: BLE001 - non-retryable: auth, refused, etc
                logger.error("邮件发送失败 to %s: %s", recipient_email, exc, exc_info=True)
                await self._audit(recipient_email, subject, ok=False, err=str(exc))
                return False, str(exc)

        return False, str(last_err) if last_err else "unknown error"

    async def _audit(self, recipient: str, subject: str, *, ok: bool, err: str | None) -> None:
        """Persist a per-recipient send attempt to manager_activity_logs.

        Note: SMTP "success" only confirms the message was accepted by the
        relay — it cannot detect downstream bounces. The activity log
        therefore records *delivery to SMTP server*, not final delivery.
        """
        if self._db is None:
            return
        params: dict[str, Any] = {
            "recipient": recipient,
            "subject": subject,
            "error": err or "",
        }
        if self._audit_source:
            params["source"] = self._audit_source
        await log_manager_activity(
            self._db,
            actor=self._actor,
            category=self._log_category,
            status="success" if ok else "fail",
            detail_key="email_sent" if ok else "email_failed",
            detail_params=params,
        )


async def send_email(
    db: AsyncSession,
    *,
    recipient_email: str,
    subject: str,
    main_content_raw: str,
    greeting: str,
    action_text: str | None = None,
    action_url: str | None = None,
    actor: str = "system",
) -> tuple[bool, str | None]:
    """Single-shot send. For batch sending, prefer ``EmailClient`` directly."""
    cfg = await get_smtp_config(db)
    site_url = await get_site_url(db)
    async with EmailClient(cfg, site_url, db=db, actor=actor) as client:
        return await client.send(
            recipient_email=recipient_email,
            subject=subject,
            main_content_raw=main_content_raw,
            greeting=greeting,
            action_text=action_text,
            action_url=action_url,
        )


# Whitelist of SMTP override keys accepted by send_test_email so the API
# cannot be coerced into setting unrelated values (e.g. BRAND_NAME) for a
# single send.
_TEST_EMAIL_OVERRIDE_KEYS = frozenset({
    "SMTP_HOST", "SMTP_PORT", "SMTP_USE_SSL",
    "SMTP_PASSWORD", "SENDER_EMAIL",
})


async def send_test_email(
    db: AsyncSession,
    *,
    recipient_email: str,
    override: dict[str, Any] | None = None,
    actor: str = "system",
) -> tuple[bool, str | None]:
    """Send a one-off SMTP test email.

    Loads the saved SMTP config and layers ``override`` on top — any keys
    outside ``_TEST_EMAIL_OVERRIDE_KEYS`` are ignored. The body is a fixed
    canned message; templates are not involved so a misconfigured template
    cannot block SMTP verification.
    """
    cfg = await get_smtp_config(db)
    if override:
        for k, v in override.items():
            if k in _TEST_EMAIL_OVERRIDE_KEYS and v not in (None, ""):
                cfg[k] = v
    site_url = await get_site_url(db)
    store = get_settings_store()
    brand_name = str(await store.get(db, "BRAND_NAME", SETTINGS_SPECS["BRAND_NAME"].default_value()))
    async with EmailClient(cfg, site_url, db=db, actor=actor, log_category="settings") as client:
        return await client.send(
            recipient_email=recipient_email,
            subject=f"[{brand_name}] SMTP 配置测试邮件",
            main_content_raw=(
                f"这是一封来自 {brand_name} 的 SMTP 配置测试邮件。\n"
                "如果您收到了这封邮件，说明当前 SMTP 配置工作正常。"
            ),
            greeting="您好！",
        )


# ── Alert email ──

ALERT_TYPE_LABELS: dict[str, str] = {
    "node_offline": "节点离线",
    "agent_only_down": "Agent 离线 (Wings 正常)",
    "wings_only_down": "Wings 离线 (Agent 正常)",
    "cpu_high": "CPU 使用率过高",
    "mem_high": "内存使用率过高",
    "swap_high": "Swap 使用率过高",
    "disk_high": "磁盘使用率告警",
    "disk_critical": "磁盘使用率严重",
    "load_high": "系统负载过高",
    "network_down": "公网探针失败",
    "clash_down": "Clash 代理探针失败",
    "cert_source_unknown": "证书源状态未知",
    "cert_source_expiring": "证书源即将过期",
    "cert_deployment_outdated": "证书部署落后",
    "cert_deployment_unreachable": "证书部署目标不可达",
}

SEVERITY_LABELS: dict[str, str] = {
    "warning": "警告",
    "critical": "严重",
    "info": "提示",
}


def alert_type_label(alert_type: str) -> str:
    return ALERT_TYPE_LABELS.get(alert_type, alert_type)


def severity_label(severity: str) -> str:
    return SEVERITY_LABELS.get(severity, severity)


async def send_alert_email(
    db: AsyncSession,
    *,
    recipient_email: str,
    host_name: str,
    host_id: int | None,
    alert_type: str,
    severity: str,
    message: str,
    fired_at: datetime,
    resolved_at: datetime | None = None,
    kind: str = "fired",
) -> tuple[bool, str | None]:
    """Render and send an alert email to a single recipient.

    ``kind`` is ``"fired"`` or ``"resolved"`` and selects the template.
    """
    template_key = "alert_resolved" if kind == "resolved" else "alert_fired"
    template = await load_template(db, template_key)
    if not template.subject and not template.body:
        return False, f"missing template: {template_key}"

    site_url = await get_site_url(db)
    store = get_settings_store()
    brand_name = str(await store.get(db, "BRAND_NAME", SETTINGS_SPECS["BRAND_NAME"].default_value()))
    variables: dict[str, Any] = {
        "brand_name": brand_name,
        "node_name": host_name,
        "node_id": "" if host_id is None else str(host_id),
        "alert_type": alert_type,
        "alert_type_label": alert_type_label(alert_type),
        "severity": severity,
        "severity_label": severity_label(severity),
        "message": message or "",
        "fired_at": fired_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "resolved_at": resolved_at.strftime("%Y-%m-%d %H:%M:%S UTC") if resolved_at else "",
    }
    rendered_subject, rendered_body = render_template_body(template, variables)

    greeting = "尊敬的管理员："
    action_text = "查看监控面板"
    action_url = f"{site_url}/#/admin/dashboard" if site_url else None

    return await send_email(
        db,
        recipient_email=recipient_email,
        subject=rendered_subject,
        main_content_raw=rendered_body,
        greeting=greeting,
        action_text=action_text,
        action_url=action_url,
    )
