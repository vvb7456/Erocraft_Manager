"""Admin email template routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.db.models.pterodactyl import PteroUser
from app.schemas.email_templates import (
    EmailMessageResponse,
    EmailTemplatePayload,
    EmailTemplatePreviewRequest,
    EmailTemplatePreviewResponse,
    EmailTemplatesResponse,
    SaveEmailTemplateRequest,
)
from app.services.audit import log_manager_activity
from app.services.email import (
    EMAIL_TEMPLATE_API_TO_INTERNAL,
    build_template_preview,
    load_all_templates,
    save_template,
)

router = APIRouter(tags=["email_templates"])

@router.get("/email-templates", response_model=EmailTemplatesResponse)
async def get_email_templates(
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EmailTemplatesResponse:
    templates = await load_all_templates(db)
    return EmailTemplatesResponse(
        bulk=EmailTemplatePayload(subject=templates["bulk"].subject, body=templates["bulk"].body),
        reminder=EmailTemplatePayload(subject=templates["reminder"].subject, body=templates["reminder"].body),
        preDelete=EmailTemplatePayload(subject=templates["pre_delete"].subject, body=templates["pre_delete"].body),
        createUser=EmailTemplatePayload(subject=templates["create_user"].subject, body=templates["create_user"].body),
        passwordReset=EmailTemplatePayload(subject=templates["password_reset"].subject, body=templates["password_reset"].body),
        emailChange=EmailTemplatePayload(subject=templates["email_change"].subject, body=templates["email_change"].body),
    )


@router.post("/email-templates", response_model=EmailMessageResponse)
async def update_email_template(
    payload: SaveEmailTemplateRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EmailMessageResponse:
    template_type = EMAIL_TEMPLATE_API_TO_INTERNAL[payload.type]
    await save_template(
        db,
        template_type,
        subject=payload.subject,
        body=payload.body,
    )
    await log_manager_activity(
        db,
        actor=current_user.username,
        action="settings",
        status="success",
        detail_key="email_template_change",
        detail_params={"template": payload.type},
    )
    return EmailMessageResponse(message="模板已保存")


@router.post("/email-templates/preview", response_model=EmailTemplatePreviewResponse)
async def preview_email_template(
    payload: EmailTemplatePreviewRequest,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EmailTemplatePreviewResponse:
    rendered_subject, html = await build_template_preview(
        db,
        template_type=payload.type,
        subject=payload.subject,
        body=payload.body,
        theme=payload.theme,
    )
    return EmailTemplatePreviewResponse(
        renderedSubject=rendered_subject,
        html=html,
    )
