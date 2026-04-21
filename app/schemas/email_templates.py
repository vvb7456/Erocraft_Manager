"""Schemas for email template management routes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr


# Every editable template type is enumerated once so the FastAPI/Pydantic
# Literal stays in lock-step with EMAIL_TEMPLATE_API_TO_INTERNAL.
TemplateTypeLiteral = Literal[
    "bulk", "reminder", "preDelete", "createUser",
    "passwordReset", "emailChange",
    "alertFired", "alertResolved",
]


class EmailTemplatePayload(BaseModel):
    subject: str
    body: str


class EmailTemplatePreviewRequest(BaseModel):
    type: TemplateTypeLiteral
    subject: str
    body: str
    theme: Literal["dark", "light"] = "light"


class EmailTemplatePreviewResponse(BaseModel):
    renderedSubject: str
    html: str


class EmailTemplatesResponse(BaseModel):
    bulk: EmailTemplatePayload
    reminder: EmailTemplatePayload
    preDelete: EmailTemplatePayload
    createUser: EmailTemplatePayload
    passwordReset: EmailTemplatePayload
    emailChange: EmailTemplatePayload
    alertFired: EmailTemplatePayload
    alertResolved: EmailTemplatePayload


class SaveEmailTemplateRequest(BaseModel):
    type: TemplateTypeLiteral
    subject: str
    body: str


class EmailMessageResponse(BaseModel):
    message: str


class TestEmailRequest(BaseModel):
    """Send a one-off test email using either saved or in-memory SMTP overrides.

    When ``smtpOverride`` is set, those values temporarily replace the saved
    SMTP_* settings for this single send. Useful for the SMTP tab "send test
    email" button so the admin can verify draft credentials without saving.
    """
    recipient: EmailStr
    smtpOverride: dict[str, str | int | bool] | None = None


class TestEmailResponse(BaseModel):
    ok: bool
    error: str | None = None
