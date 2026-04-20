"""Schemas for email template management routes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class EmailTemplatePayload(BaseModel):
    subject: str
    body: str


class EmailTemplatePreviewRequest(BaseModel):
    type: Literal["bulk", "reminder", "preDelete", "createUser", "passwordReset", "emailChange"]
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


class SaveEmailTemplateRequest(BaseModel):
    type: Literal["bulk", "reminder", "preDelete", "createUser", "passwordReset", "emailChange"]
    subject: str
    body: str


class EmailMessageResponse(BaseModel):
    message: str
