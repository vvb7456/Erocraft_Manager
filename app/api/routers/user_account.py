"""User account self-service routes."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.core.runtime_settings import SETTINGS_SPECS
from app.core.settings_store import get_settings_store
from app.core.tokens import hash_token, verify_token
from app.db.models.manager import ManagerEmailChange, ManagerPasswordReset
from app.db.models.pterodactyl import PteroUser
from app.db.repositories.users import user_repository
from app.schemas.user_account import (
    UpdateUserAccountRequest,
    UpdateUserAccountResponse,
    UserAccountProfileResponse,
)
from app.services.audit import log_manager_activity
from app.services.email import get_site_url, load_template, render_template_body, send_email
from app.services.pterodactyl import PterodactylServiceError, pterodactyl_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/user", tags=["user_account"])

EMAIL_CHANGE_EXPIRY_MINUTES = 30


def _build_profile(user: PteroUser) -> UserAccountProfileResponse:
    return UserAccountProfileResponse(
        id=int(user.id),
        username=user.username,
        email=user.email,
        is_admin=bool(user.root_admin),
    )


@router.get("/me", response_model=UserAccountProfileResponse)
async def get_user_profile(
    current_user: PteroUser = Depends(get_current_user),
) -> UserAccountProfileResponse:
    return _build_profile(current_user)


@router.patch("/account", response_model=UpdateUserAccountResponse)
async def update_user_account(
    payload: UpdateUserAccountRequest,
    current_user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UpdateUserAccountResponse:
    current_password = (payload.currentPassword or "").strip()
    new_password = (payload.newPassword or "").strip() or None

    if not new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account.password_required")

    if not current_user.check_password(current_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="account.current_password_incorrect")

    try:
        await pterodactyl_service.update_user(
            int(current_user.id),
            email=current_user.email,
            username=current_user.username,
            first_name=current_user.name_first or current_user.username,
            last_name=current_user.name_last or "User",
            password=new_password,
        )
    except PterodactylServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="account.password_update_failed") from exc

    await db.execute(
        update(ManagerPasswordReset)
        .where(ManagerPasswordReset.user_id == int(current_user.id))
        .where(ManagerPasswordReset.used_at.is_(None))
        .values(used_at=datetime.now(UTC).replace(tzinfo=None))
    )
    await db.commit()

    await log_manager_activity(
        db,
        actor=current_user.username,
        action="account",
        status="success",
        detail_key="user_password_changed",
        detail_params={"username": current_user.username},
    )
    return UpdateUserAccountResponse(message="密码已修改", user=_build_profile(current_user))


# ── Change email (requires old email verification) ──

class ChangeEmailRequest(BaseModel):
    newEmail: EmailStr


class ChangeEmailResponse(BaseModel):
    message: str


@router.post("/account/change-email", response_model=ChangeEmailResponse)
async def change_email(
    payload: ChangeEmailRequest,
    current_user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChangeEmailResponse:
    new_email = payload.newEmail.strip().lower()
    if new_email == current_user.email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account.email_same")

    existing = await user_repository.get_by_email(db, new_email)
    if existing and existing.id != current_user.id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="account.email_unavailable")

    cur_user_id = int(current_user.id)
    cur_username = current_user.username
    cur_email = current_user.email
    await db.execute(select(PteroUser.id).where(PteroUser.id == cur_user_id).with_for_update())

    # Rate limit: 60s
    recent = await db.execute(
        select(ManagerEmailChange)
        .where(ManagerEmailChange.user_id == cur_user_id)
        .order_by(ManagerEmailChange.created_at.desc())
        .limit(1)
    )
    last_change = recent.scalar_one_or_none()
    if last_change and last_change.created_at:
        elapsed = (datetime.now(UTC).replace(tzinfo=None) - last_change.created_at).total_seconds()
        if elapsed < 60:
            await db.rollback()
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="account.email_rate_limited")

    raw_token = secrets.token_hex(32)
    token_hash = hash_token(raw_token)

    # Invalidate all prior unused tokens for this user
    await db.execute(
        update(ManagerEmailChange)
        .where(ManagerEmailChange.user_id == cur_user_id)
        .where(ManagerEmailChange.confirmed_at.is_(None))
        .values(confirmed_at=datetime.now(UTC).replace(tzinfo=None))
    )

    change = ManagerEmailChange(
        user_id=cur_user_id,
        new_email=new_email,
        token=token_hash,
    )
    db.add(change)
    await db.flush()
    change_id = int(change.id)
    await db.commit()

    # Build confirm URL
    store = get_settings_store()
    brand_name = str(await store.get(db, "BRAND_NAME", SETTINGS_SPECS["BRAND_NAME"].default_value()))
    site_url = await get_site_url(db)
    confirm_url = f"{site_url}/#/confirm-email?token={raw_token}&uid={cur_user_id}"

    template = await load_template(db, "email_change")
    subject, body = render_template_body(
        template,
        {
            "brand_name": brand_name,
            "username": cur_username,
            "new_email": new_email,
            "confirm_url": confirm_url,
        },
    )

    success, err = await send_email(
        db,
        recipient_email=cur_email,
        subject=subject,
        main_content_raw=body,
        greeting=f"您好，{cur_username}！",
        action_text="确认更改",
        action_url=confirm_url,
    )
    if not success:
        await db.execute(delete(ManagerEmailChange).where(ManagerEmailChange.id == change_id))
        await db.commit()
        logger.error("Failed to send email change confirmation to %s: %s", cur_email, err)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="account.email_send_failed")

    await log_manager_activity(
        db,
        actor=cur_username,
        action="account",
        status="success",
        detail_key="email_change_requested",
        detail_params={"username": cur_username, "new_email": new_email},
    )
    return ChangeEmailResponse(message="验证邮件已发送到您当前的邮箱，请查收并点击确认链接。")


class ConfirmEmailRequest(BaseModel):
    token: str
    uid: int


@router.post("/account/confirm-email", response_model=ChangeEmailResponse)
async def confirm_email(
    payload: ConfirmEmailRequest,
    db: AsyncSession = Depends(get_db),
) -> ChangeEmailResponse:
    """Confirm email change — no auth required (token-based)."""
    # Find latest unused token for this specific user
    result = await db.execute(
        select(ManagerEmailChange)
        .where(ManagerEmailChange.user_id == payload.uid)
        .where(ManagerEmailChange.confirmed_at.is_(None))
        .order_by(ManagerEmailChange.created_at.desc())
        .limit(1)
    )
    record = result.scalar_one_or_none()

    if not record or not verify_token(payload.token, record.token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account.invalid_confirm_link")

    # Check expiry
    if record.created_at:
        age = datetime.now(UTC).replace(tzinfo=None) - record.created_at
        if age > timedelta(minutes=EMAIL_CHANGE_EXPIRY_MINUTES):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account.confirm_link_expired")

    # Check new email still available
    existing = await user_repository.get_by_email(db, record.new_email)
    if existing and existing.id != record.user_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="account.email_unavailable")

    user = await user_repository.get_by_id(db, record.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account.user_missing")

    old_email = user.email
    claim_time = datetime.now(UTC).replace(tzinfo=None)
    claim_result = await db.execute(
        update(ManagerEmailChange)
        .where(ManagerEmailChange.id == int(record.id))
        .where(ManagerEmailChange.confirmed_at.is_(None))
        .values(confirmed_at=claim_time)
    )
    if not claim_result.rowcount:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account.invalid_confirm_link")
    await db.commit()

    # Update via Panel API
    try:
        await pterodactyl_service.update_user(
            int(user.id),
            email=record.new_email,
            username=user.username,
            first_name=user.name_first or user.username,
            last_name=user.name_last or "User",
        )
    except PterodactylServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="account.email_confirm_status_unknown") from exc

    await log_manager_activity(
        db,
        actor=user.username,
        action="account",
        status="success",
        detail_key="email_changed",
        detail_params={"username": user.username, "old_email": old_email, "new_email": record.new_email},
    )

    return ChangeEmailResponse(message="邮箱已成功更改。")
