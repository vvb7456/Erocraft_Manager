"""Public (no-auth) routes: branding, forgot/reset password."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.db import get_db
from app.core.runtime_settings import SETTINGS_SPECS
from app.core.settings_store import get_settings_store
from app.core.tokens import hash_token, verify_token
from app.db.models.manager import ManagerPasswordReset
from app.db.models.pterodactyl import PteroUser
from app.db.repositories.users import user_repository
from app.services.audit import log_manager_activity
from app.services.email import get_site_url, load_template, render_template_body, send_email

logger = logging.getLogger(__name__)
router = APIRouter(tags=["public"])

TOKEN_EXPIRY_MINUTES = 30
FORGOT_PASSWORD_GENERIC_MESSAGE = "如果该邮箱已注册，您将收到密码重置链接。"


# ── Schemas ──

class BrandingResponse(BaseModel):
    brand_name: str


class ForgotPasswordRequest(BaseModel):
    email: str


class MessageResponse(BaseModel):
    message: str


class ResetPasswordRequest(BaseModel):
    email: str
    token: str
    newPassword: str = Field(min_length=8, max_length=72)


# ── Helpers ──

async def _brand_name(db: AsyncSession) -> str:
    store = get_settings_store()
    return str(await store.get(db, "BRAND_NAME", SETTINGS_SPECS["BRAND_NAME"].default_value()))


async def _site_url(db: AsyncSession) -> str:
    return await get_site_url(db)


# ── Routes ──

@router.get("/public/branding", response_model=BrandingResponse)
async def get_branding(db: AsyncSession = Depends(get_db)) -> BrandingResponse:
    return BrandingResponse(brand_name=await _brand_name(db))


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    email = payload.email.strip().lower()
    if not email:
        return MessageResponse(message=FORGOT_PASSWORD_GENERIC_MESSAGE)

    user = await user_repository.get_by_email(db, email)
    if not user:
        return MessageResponse(message=FORGOT_PASSWORD_GENERIC_MESSAGE)

    user_id = int(user.id)
    username = user.username
    await db.execute(select(PteroUser.id).where(PteroUser.id == user_id).with_for_update())

    # Rate limit: 60s per email
    recent = await db.execute(
        select(ManagerPasswordReset)
        .where(ManagerPasswordReset.user_id == user_id)
        .order_by(ManagerPasswordReset.created_at.desc())
        .limit(1)
    )
    last_reset = recent.scalar_one_or_none()
    if last_reset and last_reset.created_at:
        elapsed = (datetime.now(UTC).replace(tzinfo=None) - last_reset.created_at).total_seconds()
        if elapsed < 60:
            await db.rollback()
            return MessageResponse(message=FORGOT_PASSWORD_GENERIC_MESSAGE)

    raw_token = secrets.token_hex(32)
    token_hash = hash_token(raw_token)

    # Invalidate all prior unused tokens for this user
    await db.execute(
        update(ManagerPasswordReset)
        .where(ManagerPasswordReset.user_id == user_id)
        .where(ManagerPasswordReset.used_at.is_(None))
        .values(used_at=datetime.now(UTC).replace(tzinfo=None))
    )

    reset = ManagerPasswordReset(
        user_id=user_id,
        token=token_hash,
    )
    db.add(reset)
    await db.flush()
    reset_id = int(reset.id)
    await db.commit()

    # Build reset URL
    brand_name = await _brand_name(db)
    site_url = await _site_url(db)
    reset_url = f"{site_url}/#/reset-password?token={raw_token}&email={email}"

    template = await load_template(db, "password_reset")
    subject, body = render_template_body(
        template,
        {
            "brand_name": brand_name,
            "username": username,
            "email": email,
            "reset_url": reset_url,
        },
    )

    success, err = await send_email(
        db,
        recipient_email=email,
        subject=subject,
        main_content_raw=body,
        greeting=f"您好，{username}！",
        action_text="重置密码",
        action_url=reset_url,
    )
    if success:
        pass
    else:
        await db.execute(delete(ManagerPasswordReset).where(ManagerPasswordReset.id == reset_id))
        await db.commit()
        logger.error("Failed to send password reset email to %s: %s", email, err)

    await log_manager_activity(
        db,
        actor=username,
        action="auth",
        status="success" if success else "failure",
        detail_key="forgot_password",
        detail_params={"username": username, "email": email},
    )

    return MessageResponse(message=FORGOT_PASSWORD_GENERIC_MESSAGE)


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    email = payload.email.strip().lower()
    user = await user_repository.get_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account.invalid_reset_link")

    # Find latest unused reset token for this user
    result = await db.execute(
        select(ManagerPasswordReset)
        .where(ManagerPasswordReset.user_id == int(user.id))
        .where(ManagerPasswordReset.used_at.is_(None))
        .order_by(ManagerPasswordReset.created_at.desc())
        .limit(1)
    )
    reset_record = result.scalar_one_or_none()
    if not reset_record:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account.invalid_reset_link")

    # Check expiry
    if reset_record.created_at:
        age = datetime.now(UTC).replace(tzinfo=None) - reset_record.created_at
        if age > timedelta(minutes=TOKEN_EXPIRY_MINUTES):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account.reset_link_expired")

    # Verify token
    if not verify_token(payload.token, reset_record.token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account.invalid_reset_link")

    claim_time = datetime.now(UTC).replace(tzinfo=None)
    claim_result = await db.execute(
        update(ManagerPasswordReset)
        .where(ManagerPasswordReset.id == int(reset_record.id))
        .where(ManagerPasswordReset.used_at.is_(None))
        .values(used_at=claim_time)
    )
    if not claim_result.rowcount:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account.invalid_reset_link")
    await db.commit()

    # Sync to Panel API — this updates the password in the DB directly
    from app.services.pterodactyl import PterodactylServiceError, pterodactyl_service
    try:
        await pterodactyl_service.update_user(
            int(user.id),
            email=user.email,
            username=user.username,
            first_name=user.name_first or user.username,
            last_name=user.name_last or "User",
            password=payload.newPassword,
        )
    except PterodactylServiceError as exc:
        logger.exception("Failed to sync password to Panel for user %s", user.username)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="account.password_reset_status_unknown",
        ) from exc

    await log_manager_activity(
        db,
        actor=user.username,
        action="auth",
        status="success",
        detail_key="reset_password",
        detail_params={"username": user.username},
    )

    return MessageResponse(message="密码已重置，请使用新密码登录。")
