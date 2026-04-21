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
    TestEmailRequest,
    TestEmailResponse,
)
from app.services.audit import log_manager_activity
from app.services.email import (
    EMAIL_TEMPLATE_API_TO_INTERNAL,
    build_template_preview,
    load_all_templates,
    save_template,
    send_test_email,
)

router = APIRouter(tags=["email_templates"])

@router.get("/email-templates", response_model=EmailTemplatesResponse)
async def get_email_templates(
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EmailTemplatesResponse:
    templates = await load_all_templates(db)

    def _payload(internal_key: str) -> EmailTemplatePayload:
        t = templates[internal_key]
        return EmailTemplatePayload(subject=t.subject, body=t.body)

    return EmailTemplatesResponse(
        bulk=_payload("bulk"),
        reminder=_payload("reminder"),
        preDelete=_payload("pre_delete"),
        createUser=_payload("create_user"),
        passwordReset=_payload("password_reset"),
        emailChange=_payload("email_change"),
        alertFired=_payload("alert_fired"),
        alertResolved=_payload("alert_resolved"),
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


@router.post("/test-email", response_model=TestEmailResponse)
async def send_smtp_test_email(
    payload: TestEmailRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TestEmailResponse:
    """Send a one-off test email using saved or in-memory SMTP settings.

    Triggered from the SMTP settings tab. Uses the saved store as the base
    config, then layers ``smtpOverride`` on top so the admin can verify
    edits *before* persisting them via the global save bar.
    """
    ok, err = await send_test_email(
        db,
        recipient_email=str(payload.recipient),
        override=payload.smtpOverride,
        actor=current_user.username,
    )
    await log_manager_activity(
        db,
        actor=current_user.username,
        action="settings",
        status="success" if ok else "fail",
        detail_key="test_email_sent",
        detail_params={"recipient": str(payload.recipient), "error": err or ""},
    )
    return TestEmailResponse(ok=ok, error=err)
