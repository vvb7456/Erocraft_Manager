"""Public (no-auth) routes: branding, forgot/reset password, public registration."""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.db import get_db
from app.core.rate_limit import limiter
from app.core.runtime_settings import SETTINGS_SPECS
from app.core.security import SESSION_USER_ID_KEY
from app.core.settings_store import get_settings_store
from app.core.tokens import (
    compute_lookup_hash,
    hash_token_async,
    verify_token_async,
)
from app.db.models.manager import ManagerPasswordReset, ManagerPendingRegistration
from app.db.models.pterodactyl import PteroUser
from app.db.repositories.users import user_repository
from app.services import panel_db
from app.services.audit import log_manager_activity
from app.services.email import (
    SiteUrlNotConfiguredError,
    get_site_url,
    load_template,
    render_template_body,
    send_email,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["public"])

TOKEN_EXPIRY_MINUTES = 30
REGISTER_TOKEN_EXPIRY_MINUTES = 30
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")
FORGOT_PASSWORD_GENERIC_MESSAGE = "如果该邮箱已注册，您将收到密码重置链接。"


# ── Schemas ──

class BrandingResponse(BaseModel):
    brand_name: str
    allow_registration: bool
    support_email: str = ""
    support_qq_group: str = ""
    support_qq: str = ""
    support_wechat: str = ""
    support_footer_note: str = ""


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class MessageResponse(BaseModel):
    message: str


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    token: str
    newPassword: str = Field(min_length=8, max_length=72)


# ── Helpers ──

async def _brand_name(db: AsyncSession) -> str:
    store = get_settings_store()
    return str(await store.get(db, "BRAND_NAME", SETTINGS_SPECS["BRAND_NAME"].default_value()))


async def _site_url(db: AsyncSession) -> str:
    return await get_site_url(db)


async def _site_url_or_503(db: AsyncSession, *, detail_key: str) -> str:
    """get_site_url with HTTPException 503 conversion for user-facing flows."""
    try:
        return await get_site_url(db)
    except SiteUrlNotConfiguredError:
        logger.error("SITE_URL not configured; aborting flow %s", detail_key)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail_key
        ) from None


# ── Routes ──

@router.get("/public/branding", response_model=BrandingResponse)
async def get_branding(db: AsyncSession = Depends(get_db)) -> BrandingResponse:
    store = get_settings_store()
    keys = (
        "BRAND_NAME", "ALLOW_PUBLIC_REGISTRATION",
        "SUPPORT_EMAIL", "SUPPORT_QQ_GROUP", "SUPPORT_QQ",
        "SUPPORT_WECHAT", "SUPPORT_FOOTER_NOTE",
    )
    defaults = {k: SETTINGS_SPECS[k].default_value() for k in keys}
    values = await store.get_many(db, defaults)
    return BrandingResponse(
        brand_name=str(values["BRAND_NAME"]),
        allow_registration=bool(values["ALLOW_PUBLIC_REGISTRATION"]),
        support_email=str(values["SUPPORT_EMAIL"] or ""),
        support_qq_group=str(values["SUPPORT_QQ_GROUP"] or ""),
        support_qq=str(values["SUPPORT_QQ"] or ""),
        support_wechat=str(values["SUPPORT_WECHAT"] or ""),
        support_footer_note=str(values["SUPPORT_FOOTER_NOTE"] or ""),
    )


@router.post("/forgot-password", response_model=MessageResponse)
@limiter.limit("5/minute")
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
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
    token_hash = await hash_token_async(raw_token)

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
    site_url = await _site_url_or_503(db, detail_key="forgot_password.site_url_not_configured")
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
        category="auth",
        status="success" if success else "failure",
        detail_key="forgot_password",
        detail_params={"username": username, "email": email},
    )

    return MessageResponse(message=FORGOT_PASSWORD_GENERIC_MESSAGE)


@router.post("/reset-password", response_model=MessageResponse)
@limiter.limit("10/minute")
async def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
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
    if not await verify_token_async(payload.token, reset_record.token):
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

    # Sync to panel via direct DB write
    from app.services import server_lifecycle
    from app.services.server_lifecycle import LifecycleError
    try:
        await server_lifecycle.update_user(
            db,
            int(user.id),
            email=user.email,
            username=user.username,
            first_name=user.name_first or user.username,
            last_name=user.name_last or "User",
            password=payload.newPassword,
        )
        await db.commit()
    except LifecycleError as exc:
        logger.exception("Failed to sync password to panel for user %s", user.username)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="account.password_reset_status_unknown",
        ) from exc

    await log_manager_activity(
        db,
        actor=user.username,
        category="auth",
        status="success",
        detail_key="reset_password",
        detail_params={"username": user.username},
    )

    return MessageResponse(message="密码已重置，请使用新密码登录。")


# ── Public registration ──

class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=72)
    first_name: str = Field(default="", max_length=255)
    last_name: str = Field(default="", max_length=255)


class VerifyRegisterRequest(BaseModel):
    token: str


class RegisterVerifyResponse(BaseModel):
    message: str
    auto_login: bool = False
    username: str | None = None
    is_admin: bool = False


async def _allow_registration(db: AsyncSession) -> bool:
    store = get_settings_store()
    return bool(
        await store.get(
            db,
            "ALLOW_PUBLIC_REGISTRATION",
            SETTINGS_SPECS["ALLOW_PUBLIC_REGISTRATION"].default_value(),
        )
    )


@router.post("/register", response_model=MessageResponse)
@limiter.limit("5/minute")
async def register(
    payload: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    if not await _allow_registration(db):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="register.disabled")

    # SITE_URL must exist before we even build the verify_url. Bail out
    # *before* hashing / sending so the user gets a fast, accurate error.
    site_url = await _site_url_or_503(db, detail_key="register.site_url_not_configured")

    email = str(payload.email).strip().lower()
    username = payload.username.strip()

    if not USERNAME_RE.match(username):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="register.invalid_username")

    # Conflict checks against the panel users table
    if await user_repository.get_by_email(db, email):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="register.email_taken")
    if await user_repository.get_by_username(db, username):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="register.username_taken")

    # Conflict checks against unfinished pending registrations
    pending_user = await db.execute(
        select(ManagerPendingRegistration)
        .where(
            ManagerPendingRegistration.username == username,
            ManagerPendingRegistration.used_at.is_(None),
        )
        .limit(1)
    )
    if pending_user.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="register.username_taken")

    # ── Serialize concurrent POST /register for the same email ──
    # Two requests can race here (e.g. a double-submitted form). The
    # idx_pr_email index lets InnoDB take a next-key gap lock on the
    # ``email`` column even when no row matches, so a second concurrent
    # request blocks on this SELECT...FOR UPDATE until the first commits
    # or rolls back. Without this, both branches read "no pending",
    # both insert, and both send a verification email — producing the
    # duplicate-second register_request entries seen in audit logs.
    now = datetime.now(UTC).replace(tzinfo=None)
    token_alive_after = now - timedelta(minutes=REGISTER_TOKEN_EXPIRY_MINUTES)
    pending_rows = (
        await db.execute(
            select(ManagerPendingRegistration)
            .where(ManagerPendingRegistration.email == email)
            .order_by(ManagerPendingRegistration.id.desc())
            .with_for_update()
        )
    ).scalars().all()

    # ── Refuse to re-send while the previous verification link is live ──
    # The link itself (30 min TTL) is the only bound we need on email
    # frequency: while it's valid, the user can finish registration with
    # the email already in their inbox, so emitting a second one is
    # both spam and a vector for mail-bomb abuse.
    active_pending = next(
        (
            row for row in pending_rows
            if row.used_at is None
            and row.created_at is not None
            and row.created_at > token_alive_after
        ),
        None,
    )
    if active_pending:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="register.verification_pending",
        )

    # Bake a $2y$ bcrypt hash up-front so we don't have to keep the plaintext.
    # Run off the event loop because bcrypt(rounds=10) takes ~70ms.
    def _hash_password(pw: str) -> str:
        h = bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")
        return ("$2y$" + h[4:]) if h.startswith("$2b$") else h

    raw_hash = await asyncio.to_thread(_hash_password, payload.password)

    raw_token = secrets.token_hex(32)
    token_hash = await hash_token_async(raw_token)
    lookup_hash = compute_lookup_hash(raw_token)

    # Invalidate any prior unused pending rows for this email so the link
    # in the latest email is the only one that works. (At this point any
    # surviving rows are already past the token TTL window; this is a
    # housekeeping mark.)
    await db.execute(
        update(ManagerPendingRegistration)
        .where(
            ManagerPendingRegistration.email == email,
            ManagerPendingRegistration.used_at.is_(None),
        )
        .values(used_at=now)
    )

    pending = ManagerPendingRegistration(
        email=email,
        username=username,
        first_name=(payload.first_name or username).strip(),
        last_name=(payload.last_name or "User").strip(),
        password_hash=raw_hash,
        token=token_hash,
        lookup_hash=lookup_hash,
    )
    db.add(pending)
    await db.flush()
    pending_id = int(pending.id)
    await db.commit()

    brand_name = await _brand_name(db)
    verify_url = f"{site_url}/#/verify-email?token={raw_token}"

    template = await load_template(db, "register_verify")
    subject, body = render_template_body(
        template,
        {
            "brand_name": brand_name,
            "username": username,
            "email": email,
            "verify_url": verify_url,
        },
    )

    success, err = await send_email(
        db,
        recipient_email=email,
        subject=subject,
        main_content_raw=body,
        greeting=f"您好，{username}！",
        action_text="验证邮箱并完成注册",
        action_url=verify_url,
    )
    if not success:
        await db.execute(
            delete(ManagerPendingRegistration).where(
                ManagerPendingRegistration.id == pending_id
            )
        )
        await db.commit()
        logger.error("Failed to send registration email to %s: %s", email, err)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="register.email_send_failed"
        )

    await log_manager_activity(
        db,
        actor=username,
        category="auth",
        status="success",
        detail_key="register_request",
        detail_params={"username": username, "email": email},
    )

    return MessageResponse(message="验证邮件已发送，请查收并点击邮件中的链接完成注册。")


@router.post("/register/verify", response_model=RegisterVerifyResponse)
@limiter.limit("10/minute")
async def verify_registration(
    payload: VerifyRegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RegisterVerifyResponse:
    raw_token = (payload.token or "").strip()
    if not raw_token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="register.invalid_token")

    # O(1) lookup via SHA-256 lookup_hash; bcrypt verify still required to
    # actually authorize (defends against DB read).
    lookup = compute_lookup_hash(raw_token)
    pending = (
        await db.execute(
            select(ManagerPendingRegistration)
            .where(ManagerPendingRegistration.lookup_hash == lookup)
            .limit(1)
        )
    ).scalar_one_or_none()

    if pending is None or not await verify_token_async(raw_token, pending.token):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="register.invalid_token")

    # Distinguish already-used vs expired vs valid for clearer UX.
    if pending.used_at is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="register.token_used")

    if pending.created_at:
        age = datetime.now(UTC).replace(tzinfo=None) - pending.created_at
        if age > timedelta(minutes=REGISTER_TOKEN_EXPIRY_MINUTES):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="register.token_expired")

    # Last-second conflict check (someone else might have grabbed the email
    # / username between sign-up and verify).
    if await user_repository.get_by_email(db, pending.email):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="register.email_taken")
    if await user_repository.get_by_username(db, pending.username):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="register.username_taken")

    # Atomically claim the pending row so a double-click can't create two users
    claim_time = datetime.now(UTC).replace(tzinfo=None)
    claim = await db.execute(
        update(ManagerPendingRegistration)
        .where(
            ManagerPendingRegistration.id == pending.id,
            ManagerPendingRegistration.used_at.is_(None),
        )
        .values(used_at=claim_time)
    )
    if not claim.rowcount:
        await db.rollback()
        # Lost the race: someone else already claimed (or the row was
        # marked used between our check and update). Surface as token_used
        # so the user can just go log in.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="register.token_used")
    await db.commit()

    try:
        created = await panel_db.create_user_with_hashed_password(
            db,
            username=pending.username,
            email=pending.email,
            first_name=pending.first_name or pending.username,
            last_name=pending.last_name or "User",
            password_hash=pending.password_hash,
        )
        await db.commit()
    except panel_db.PanelDBError as exc:
        # Roll back the claim so the user can retry / re-register.
        try:
            await db.execute(
                update(ManagerPendingRegistration)
                .where(ManagerPendingRegistration.id == pending.id)
                .values(used_at=None)
            )
            await db.commit()
        except Exception:
            logger.exception("Failed to revert pending claim for id=%s", pending.id)
        logger.error("create_user (public register) failed for %s: %s", pending.email, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="register.create_failed"
        ) from exc

    await log_manager_activity(
        db,
        actor=created.username,
        category="auth",
        status="success",
        detail_key="register_verified",
        detail_params={"username": created.username, "email": created.email},
    )

    # Auto-login: set the session cookie so the user lands directly on the
    # app instead of being asked to log in immediately after verifying.
    request.session.clear()
    request.session[SESSION_USER_ID_KEY] = int(created.id)

    return RegisterVerifyResponse(
        message="邮箱验证成功，账户已激活。",
        auto_login=True,
        username=created.username,
        is_admin=False,
    )
