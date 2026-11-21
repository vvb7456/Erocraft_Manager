"""User account self-service routes."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.core.api_errors import ApiError
from app.core.contracts import OperationResult
from app.core.rate_limit import limiter
from app.core.runtime_settings import SETTINGS_SPECS
from app.core.settings_store import get_settings_store
from app.db.models.manager import ManagerPasswordReset
from app.db.models.pterodactyl import PteroUser
from app.db.repositories.users import user_repository
from app.schemas.user_account import (
    UpdateLanguageRequest,
    UpdateUserAccountRequest,
    UpdateUserAccountResponse,
    UserAccountProfileResponse,
)
from app.services import server_lifecycle
from app.services import verification_codes as code_svc
from app.services.audit import log_manager_activity
from app.services.email import (
    SiteUrlNotConfiguredError,
    get_site_url,
    load_template,
    render_template_body,
    send_email,
)
from app.services.server_lifecycle import LifecycleError
from app.services.user.validation import normalize_email

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/user", tags=["user_account"])


def _build_profile(user: PteroUser) -> UserAccountProfileResponse:
    return UserAccountProfileResponse(
        id=int(user.id),
        username=user.username,
        email=user.email,
        is_admin=bool(user.root_admin),
        language=user.language or "zh",
    )


@router.get("/me", response_model=UserAccountProfileResponse)
async def get_user_profile(
    current_user: PteroUser = Depends(get_current_user),
) -> UserAccountProfileResponse:
    return _build_profile(current_user)


@router.patch("/account", response_model=UpdateUserAccountResponse)
@limiter.limit("10/minute")
async def update_user_account(
    payload: UpdateUserAccountRequest,
    request: Request,
    current_user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UpdateUserAccountResponse:
    current_password = payload.currentPassword
    new_password = payload.newPassword

    if not new_password:
        raise ApiError(422, "account.password_required")

    valid_current = (
        len(current_password.encode("utf-8")) <= 72
        and await asyncio.to_thread(current_user.check_password, current_password)
    )
    if not valid_current:
        raise ApiError(422, "account.current_password_incorrect")

    try:
        await server_lifecycle.update_user(
            db,
            int(current_user.id),
            email=current_user.email,
            username=current_user.username,
            first_name=current_user.name_first or current_user.username,
            last_name=current_user.name_last or "User",
            password=new_password,
        )
    except LifecycleError as exc:
        raise ApiError(502, "account.password_update_failed") from exc

    now = datetime.now(UTC).replace(tzinfo=None)
    await db.execute(
        update(ManagerPasswordReset)
        .where(ManagerPasswordReset.user_id == int(current_user.id))
        .where(ManagerPasswordReset.used_at.is_(None))
        .values(used_at=now)
    )
    await code_svc.revoke_user_codes(db, int(current_user.id), now)
    await db.commit()

    await log_manager_activity(
        db,
        actor=current_user.username,
        category="user",
        operation=OperationResult(
            action="user.password.update",
            phase="execution",
            outcome="success",
            target={"user_id": current_user.id},
        ),
        detail_key="user_password_changed",
        detail_params={"username": current_user.username},
    )
    return UpdateUserAccountResponse(message="密码已修改", user=_build_profile(current_user))


# ── Change email (verification code sent to new email + current password on confirm) ──

class ChangeEmailRequest(BaseModel):
    newEmail: EmailStr = Field(max_length=191)


class ChangeEmailResponse(BaseModel):
    message: str
    user: UserAccountProfileResponse | None = None


class ConfirmEmailRequest(BaseModel):
    newEmail: EmailStr = Field(max_length=191)
    code: str = Field(min_length=1, max_length=32)
    currentPassword: str = ""


@router.patch("/account/language", response_model=UserAccountProfileResponse)
async def update_user_language(
    payload: UpdateLanguageRequest,
    current_user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserAccountProfileResponse:
    user = await db.get(PteroUser, int(current_user.id))
    if user is None:
        raise ApiError(404, "account.user_missing")
    if user.language != payload.language:
        user.language = payload.language
        user.updated_at = datetime.now(UTC).replace(tzinfo=None)
        await db.commit()
        await db.refresh(user)
        await log_manager_activity(
            db,
            actor=user.username,
            category="user",
            operation=OperationResult(
                action="user.language.update",
                phase="execution",
                outcome="success",
                target={"user_id": user.id},
            ),
            detail_key="user_language_changed",
            detail_params={"username": user.username, "language": payload.language},
        )
    return _build_profile(user)


@router.post("/account/change-email", response_model=ChangeEmailResponse)
@limiter.limit("5/minute")
async def change_email(
    payload: ChangeEmailRequest,
    request: Request,
    current_user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChangeEmailResponse:
    new_email = normalize_email(payload.newEmail)
    if new_email == normalize_email(current_user.email):
        raise ApiError(422, "account.email_same")

    existing = await user_repository.get_by_email(db, new_email)
    if existing and existing.id != current_user.id:
        raise ApiError(409, "account.email_unavailable")

    cur_user_id = int(current_user.id)
    cur_username = current_user.username
    await db.execute(select(PteroUser.id).where(PteroUser.id == cur_user_id).with_for_update())

    now = datetime.now(UTC).replace(tzinfo=None)
    if await code_svc.is_within_cooldown(db, purpose="email_change", user_id=cur_user_id, now=now):
        await db.rollback()
        raise ApiError(429, "account.email_rate_limited")

    try:
        await get_site_url(db)
    except SiteUrlNotConfiguredError:
        await db.rollback()
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "email_change.site_url_not_configured",
        ) from None

    record_id, raw_code = await code_svc.issue_code(
        db,
        purpose="email_change",
        email=new_email,
        user_id=cur_user_id,
        now=now,
    )
    await db.commit()

    store = get_settings_store()
    brand_name = str(await store.get(db, "BRAND_NAME", SETTINGS_SPECS["BRAND_NAME"].default_value()))
    template = await load_template(db, "email_change")
    subject, body = render_template_body(
        template,
        {
            "brand_name": brand_name,
            "username": cur_username,
            "new_email": new_email,
            "verification_code": raw_code,
        },
    )

    success, err = await send_email(
        db,
        recipient_email=new_email,
        subject=subject,
        main_content_raw=body,
        greeting=f"您好，{cur_username}！",
        verification_code=raw_code,
    )
    if not success:
        await code_svc.delete_code(db, record_id)
        await db.commit()
        logger.error("Failed to send email change code to %s: %s", new_email, err)
        raise ApiError(502, "account.email_send_failed")

    await log_manager_activity(
        db,
        actor=cur_username,
        category="user",
        operation=OperationResult(
            action="user.email.update",
            phase="acceptance",
            outcome="success",
            target={"username": cur_username},
        ),
        detail_key="email_change_requested",
        detail_params={"username": cur_username, "new_email": new_email},
    )
    return ChangeEmailResponse(message="验证码已发送到您的新邮箱，请查收。")


@router.post("/account/confirm-email", response_model=ChangeEmailResponse)
@limiter.limit("10/minute")
async def confirm_email(
    payload: ConfirmEmailRequest,
    request: Request,
    current_user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChangeEmailResponse:
    """Confirm email change in-place using verification code sent to new email + current password."""
    new_email = normalize_email(payload.newEmail)
    raw_code = payload.code.strip()
    now = datetime.now(UTC).replace(tzinfo=None)

    user = (
        await db.execute(
            select(PteroUser)
            .where(PteroUser.id == int(current_user.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if user is None:
        await db.rollback()
        raise ApiError(404, "account.user_missing")

    valid_current = (
        len(payload.currentPassword.encode("utf-8")) <= 72
        and await asyncio.to_thread(user.check_password, payload.currentPassword)
    )
    if not valid_current:
        await db.rollback()
        raise ApiError(422, "account.current_password_incorrect")

    if new_email == normalize_email(user.email):
        await db.rollback()
        raise ApiError(422, "account.email_same")

    record, code_status = await code_svc.verify_latest_code(
        db,
        purpose="email_change",
        email=new_email,
        code=raw_code,
        user_id=int(user.id),
        now=now,
    )
    if code_status != "ok" or record is None:
        await db.rollback()
        raise ApiError(
            422,
            "account.email_code_expired"
            if code_status == "expired"
            else "account.invalid_email_code",
        )

    existing = await user_repository.get_by_email(db, new_email)
    if existing and existing.id != user.id:
        await db.rollback()
        raise ApiError(409, "account.email_unavailable")

    old_email = user.email
    await code_svc.consume_code(db, record, now)

    try:
        await server_lifecycle.update_user(
            db,
            int(user.id),
            email=new_email,
            username=user.username,
            first_name=user.name_first or user.username,
            last_name=user.name_last or "User",
        )
        await db.commit()
    except LifecycleError as exc:
        await db.rollback()
        raise ApiError(502, "account.email_confirm_status_unknown") from exc

    await db.refresh(user)

    await log_manager_activity(
        db,
        actor=user.username,
        category="user",
        operation=OperationResult(
            action="user.email.update",
            phase="execution",
            outcome="success",
            target={"user_id": user.id},
        ),
        detail_key="email_changed",
        detail_params={"username": user.username, "old_email": old_email, "new_email": new_email},
    )

    return ChangeEmailResponse(message="邮箱已成功更改。", user=_build_profile(user))
