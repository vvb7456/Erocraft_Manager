"""Email service — SMTP sending and template management."""

import json
import smtplib
import time
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from flask import current_app, render_template
from app.config import config_manager


# ── Template file paths ──

_TEMPLATE_FILES = {
    'bulk': 'templates/email_template.json',
    'reminder': 'templates/reminder_template.json',
    'pre_delete': 'templates/pre_delete_reminder_template.json',
    'create_user': 'templates/create_user_template.json',
}

_TEMPLATE_DEFAULTS = {
    'bulk': {
        'subject': '来自 {{panel_name}} 的通知',
        'body': '这是一封通知邮件。',
    },
    'reminder': {
        'subject': '【重要】您的服务器即将到期',
        'body': '您好！\n\n您在 {{panel_name}} 的 {{server_count}} 台服务器将于 {{expiration_date}} 到期。\n\n服务器列表:\n{{server_list}}\n\n请及时处理。',
    },
    'pre_delete': {
        'subject': '【最终警告】您的服务器将于明天被删除',
        'body': '您好！您的服务器 {{server_name}} 将于 {{deletion_date}} 被永久删除，数据无法恢复。请立即续费以保留数据。',
    },
    'create_user': {
        'subject': '欢迎！您的新账户已创建成功',
        'body': '您的账户已经成功创建。\n\n登录用户名: {{username}}\n\n请点击下方按钮前往面板设置您的密码。\n\n祝您使用愉快！',
    },
}


# ── Template CRUD ──

def load_template(template_type: str) -> dict:
    """Load an email template by type. Returns dict with at least 'subject' and 'body'."""
    filepath = _TEMPLATE_FILES.get(template_type)
    if not filepath:
        return {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_TEMPLATE_DEFAULTS.get(template_type, {}))


def save_template(template_type: str, data: dict):
    """Save an email template by type."""
    filepath = _TEMPLATE_FILES.get(template_type)
    if not filepath:
        return
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def load_all_templates() -> dict:
    """Load all 4 template types."""
    return {t: load_template(t) for t in _TEMPLATE_FILES}


# ── Send ──

def send_email(recipient_email: str, subject: str, main_content_raw: str,
               greeting: str, action_text: str | None = None,
               action_url: str | None = None) -> tuple[bool, str]:
    """Send an HTML email via SMTP.

    Returns (success: bool, message: str).
    """
    cfg = config_manager.config
    sender_email = cfg.get('SENDER_EMAIL')

    if not all([cfg.get('SMTP_HOST'), cfg.get('SMTP_PORT'), cfg.get('SMTP_PASSWORD'), sender_email]):
        msg = 'SMTP 配置不完整（主机、端口、密码、发件人地址），请检查系统设置。'
        current_app.logger.error(msg)
        return False, msg

    panel_name = config_manager.get('BRAND_NAME', 'Ptero Manager')
    panel_url = config_manager.get('PTERO_PANEL_URL')
    main_content_html = main_content_raw.replace('\n', '<br>')

    from datetime import datetime
    html_body = render_template(
        'email_base.html',
        panel_name=panel_name, panel_url=panel_url,
        greeting=greeting, main_content=main_content_html,
        action_text=action_text, action_url=action_url,
        current_year=datetime.now().year,
    )

    mime = MIMEText(html_body, 'html', 'utf-8')
    mime['From'] = formataddr((Header(panel_name, 'utf-8').encode(), sender_email))
    mime['To'] = recipient_email
    mime['Subject'] = Header(subject, 'utf-8')

    try:
        server_class = smtplib.SMTP_SSL if cfg['SMTP_USE_SSL'] else smtplib.SMTP
        raw_msg = mime.as_string()
        with server_class(cfg['SMTP_HOST'], int(cfg['SMTP_PORT']), timeout=20) as server:
            if not cfg['SMTP_USE_SSL']:
                server.starttls()
            server.login(sender_email, cfg['SMTP_PASSWORD'])
            server.sendmail(sender_email, [recipient_email], raw_msg)
        current_app.logger.info(f"邮件已成功发送至 {recipient_email}")
        return True, '发送成功'
    except Exception as e:
        current_app.logger.error(f"邮件发送失败 to {recipient_email}: {e}", exc_info=True)
        return False, str(e)


def render_template_body(template_data: dict, context: dict) -> tuple[str, str]:
    """Apply placeholder substitution on subject and body.

    Returns (rendered_subject, rendered_body).
    """
    subject = template_data.get('subject', '')
    body = template_data.get('body', '')
    for key, value in context.items():
        subject = subject.replace(key, str(value))
        body = body.replace(key, str(value))
    return subject, body


def get_email_delay() -> int:
    return config_manager.get('EMAIL_SEND_DELAY', 2)
