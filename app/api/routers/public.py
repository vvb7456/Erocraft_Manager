"""Public (no-auth) routes: branding, forgot/reset password, public registration."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.db import get_db
from app.core.api_errors import ApiError
from app.core.contracts import OperationResult
from app.core.error_codes import ErrorCode
from app.core.rate_limit import limiter
from app.core.runtime_settings import BILLING_SPECS, SETTINGS_SPECS
from app.core.security import SESSION_USER_ID_KEY
from app.core.settings_store import get_settings_store
from app.core.tokens import VERIFICATION_CODE_EXPIRY_MINUTES, verify_token_async
from app.db.models.manager import ManagerPasswordReset
from app.db.models.pterodactyl import PteroUser
from app.db.repositories.users import user_repository
from app.db.session import get_engine
from app.schemas.agreements import AcceptanceItem
from app.services import agreements as agreements_svc
from app.services import panel_db
from app.services import verification_codes as code_svc
from app.services.audit import log_manager_activity
from app.services.email import (
    SiteUrlNotConfiguredError,
    get_site_url,
    load_template,
    render_template_body,
    send_email,
)
from app.services.user.validation import NewPassword, normalize_email, normalize_username

logger = logging.getLogger(__name__)
router = APIRouter(tags=["public"])

TOKEN_EXPIRY_MINUTES = VERIFICATION_CODE_EXPIRY_MINUTES
FORGOT_PASSWORD_GENERIC_MESSAGE = "如果该邮箱已注册，您将收到密码重置验证码。"


# ── Schemas ──

class BrandingResponse(BaseModel):
    brand_name: str
    allow_registration: bool
    agreements_default_checked: bool
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
    code: str = ""
    token: str = ""
    newPassword: NewPassword


class SendRegisterCodeRequest(BaseModel):
    email: EmailStr = Field(max_length=191)


class RegisterRequest(BaseModel):
    email: EmailStr = Field(max_length=191)
    username: str = Field(max_length=255)
    code: str = Field(min_length=1, max_length=32)
    password: NewPassword
    first_name: str = Field(default="", max_length=255)
    last_name: str = Field(default="", max_length=255)
    # 8-char invite code from the referring user, optional.
    invite_code: str | None = Field(default=None, max_length=8)
    accepted_agreements: list[AcceptanceItem] = Field(default_factory=list)


class RegisterResponse(BaseModel):
    message: str
    auto_login: bool = True
    username: str | None = None
    is_admin: bool = False


# ── Helpers ──

async def _brand_name(db: AsyncSession) -> str:
    store = get_settings_store()
    return str(await store.get(db, "BRAND_NAME", SETTINGS_SPECS["BRAND_NAME"].default_value()))


async def _site_url_or_503(db: AsyncSession, *, detail_key: ErrorCode) -> str:
    """get_site_url with ApiError conversion for user-facing flows."""
    try:
        return await get_site_url(db)
    except SiteUrlNotConfiguredError:
        logger.error("SITE_URL not configured; aborting flow %s", detail_key)
        raise ApiError(409, detail_key) from None


async def _allow_registration(db: AsyncSession) -> bool:
    store = get_settings_store()
    return bool(
        await store.get(
            db,
            "ALLOW_PUBLIC_REGISTRATION",
            SETTINGS_SPECS["ALLOW_PUBLIC_REGISTRATION"].default_value(),
        )
    )


# ── Routes ──

@router.get("/public/branding", response_model=BrandingResponse)
async def get_branding(db: AsyncSession = Depends(get_db)) -> BrandingResponse:
    store = get_settings_store()
    keys = (
        "BRAND_NAME", "ALLOW_PUBLIC_REGISTRATION", "AGREEMENTS_DEFAULT_CHECKED",
        "SUPPORT_EMAIL", "SUPPORT_QQ_GROUP", "SUPPORT_QQ",
        "SUPPORT_WECHAT", "SUPPORT_FOOTER_NOTE",
    )
    defaults = {k: SETTINGS_SPECS[k].default_value() for k in keys}
    values = await store.get_many(db, defaults)
    return BrandingResponse(
        brand_name=str(values["BRAND_NAME"]),
        allow_registration=bool(values["ALLOW_PUBLIC_REGISTRATION"]),
        agreements_default_checked=bool(values["AGREEMENTS_DEFAULT_CHECKED"]),
        support_email=str(values["SUPPORT_EMAIL"] or ""),
        support_qq_group=str(values["SUPPORT_QQ_GROUP"] or ""),
        support_qq=str(values["SUPPORT_QQ"] or ""),
        support_wechat=str(values["SUPPORT_WECHAT"] or ""),
        support_footer_note=str(values["SUPPORT_FOOTER_NOTE"] or ""),
    )


@router.post("/forgot-password", response_model=MessageResponse)
@limiter.limit("5/minute;20/hour")
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    email = normalize_email(payload.email)
    if not email:
        return MessageResponse(message=FORGOT_PASSWORD_GENERIC_MESSAGE)

    user = await user_repository.get_by_email(db, email)
    if not user:
        return MessageResponse(message=FORGOT_PASSWORD_GENERIC_MESSAGE)

    user_id = int(user.id)
    username = user.username
    await db.execute(select(PteroUser.id).where(PteroUser.id == user_id).with_for_update())

    now = datetime.now(UTC).replace(tzinfo=None)
    if await code_svc.is_within_cooldown(db, purpose="password_reset", user_id=user_id, now=now):
        await db.rollback()
        return MessageResponse(message=FORGOT_PASSWORD_GENERIC_MESSAGE)

    try:
        await _site_url_or_503(db, detail_key="forgot_password.site_url_not_configured")
    except ApiError:
        await db.rollback()
        raise

    record_id, raw_code = await code_svc.issue_code(
        db,
        purpose="password_reset",
        email=email,
        user_id=user_id,
        now=now,
    )
    await db.commit()

    brand_name = await _brand_name(db)
    template = await load_template(db, "password_reset")
    subject, body = render_template_body(
        template,
        {
            "brand_name": brand_name,
            "username": username,
            "email": email,
            "verification_code": raw_code,
        },
    )

    success, err = await send_email(
        db,
        recipient_email=email,
        subject=subject,
        main_content_raw=body,
        greeting=f"您好，{username}！",
        verification_code=raw_code,
    )
    if not success:
        await code_svc.delete_code(db, record_id)
        await db.commit()
        logger.error("Failed to send password reset code email to %s: %s", email, err)

    await log_manager_activity(
        db,
        actor=username,
        category="auth",
        operation=OperationResult(
            action="auth.password_reset.email",
            phase="acceptance",
            outcome="success" if success else "failed",
            target={"username": username},
        ),
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
    email = normalize_email(payload.email)
    raw_token = payload.token.strip()
    raw_code = payload.code.strip()
    using_token = bool(raw_token)
    invalid_error: ErrorCode = (
        "account.invalid_reset_link" if using_token else "account.invalid_reset_code"
    )

    user = await user_repository.get_by_email(db, email)
    if not user:
        raise ApiError(422, invalid_error)

    user_id = int(user.id)
    now = datetime.now(UTC).replace(tzinfo=None)

    if using_token:
        result = await db.execute(
            select(ManagerPasswordReset)
            .where(ManagerPasswordReset.user_id == user_id)
            .where(ManagerPasswordReset.used_at.is_(None))
            .order_by(ManagerPasswordReset.created_at.desc(), ManagerPasswordReset.id.desc())
            .limit(1)
        )
        reset_record = result.scalar_one_or_none()
        if not reset_record:
            raise ApiError(422, "account.invalid_reset_link")

        if reset_record.created_at:
            age = now - reset_record.created_at
            if age > timedelta(minutes=TOKEN_EXPIRY_MINUTES):
                raise ApiError(422, "account.reset_link_expired")

        if not await verify_token_async(raw_token, reset_record.token):
            raise ApiError(422, "account.invalid_reset_link")

        claim_result = await db.execute(
            update(ManagerPasswordReset)
            .where(ManagerPasswordReset.id == int(reset_record.id))
            .where(ManagerPasswordReset.used_at.is_(None))
            .values(used_at=now)
        )
        if not claim_result.rowcount:
            await db.rollback()
            raise ApiError(422, "account.invalid_reset_link")
        await code_svc.revoke_user_codes(db, user_id, now)
        await db.commit()
    else:
        record, code_status = await code_svc.verify_latest_code(
            db,
            purpose="password_reset",
            email=email,
            code=raw_code,
            user_id=user_id,
            now=now,
        )
        if code_status != "ok" or record is None:
            await db.rollback()
            raise ApiError(
                422,
                "account.reset_code_expired"
                if code_status == "expired"
                else "account.invalid_reset_code",
            )
        await code_svc.consume_code(db, record, now)
        await db.execute(
            update(ManagerPasswordReset)
            .where(ManagerPasswordReset.user_id == user_id)
            .where(ManagerPasswordReset.used_at.is_(None))
            .values(used_at=now)
        )
        await code_svc.revoke_user_codes(db, user_id, now)
        await db.commit()

    from app.services import server_lifecycle
    from app.services.server_lifecycle import LifecycleError

    try:
        await server_lifecycle.update_user(
            db,
            user_id,
            email=user.email,
            username=user.username,
            first_name=user.name_first or user.username,
            last_name=user.name_last or "User",
            password=payload.newPassword,
        )
        await db.commit()
    except LifecycleError as exc:
        logger.exception("Failed to sync password for user %s", user.username)
        raise ApiError(502, "account.password_reset_status_unknown") from exc

    await log_manager_activity(
        db,
        actor=user.username,
        category="auth",
        operation=OperationResult(
            action="auth.password.reset",
            phase="execution",
            outcome="success",
            target={"user_id": user.id},
        ),
        detail_key="reset_password",
        detail_params={"username": user.username},
    )

    return MessageResponse(message="密码已重置，请使用新密码登录。")


# ── Public registration ──

@router.post("/register/code", response_model=MessageResponse)
@limiter.limit("5/minute;20/hour")
async def send_register_code(
    payload: SendRegisterCodeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    if not await _allow_registration(db):
        raise ApiError(403, "register.disabled")

    await _site_url_or_503(db, detail_key="register.site_url_not_configured")

    email = normalize_email(payload.email)
    if await user_repository.get_by_email(db, email):
        raise ApiError(409, "register.email_taken")

    # 用独立连接的 MySQL 命名锁串行化同邮箱首次发码：
    # 1) 避免空索引范围 FOR UPDATE 触发 InnoDB 间隙锁死锁；
    # 2) 确保 GET_LOCK 与 RELEASE_LOCK 始终落在同一连接上，且在 db.commit() 之后释放；
    # 3) 拿锁后先 rollback() 刷新 REPEATABLE READ 快照，确保看到前序并发请求刚提交的验证码。
    lock_name = f"erocraft:reg_code:{hashlib.sha256(email.encode()).hexdigest()[:32]}"
    async with get_engine().connect() as lock_conn:
        acquired = await lock_conn.scalar(
            text("SELECT GET_LOCK(:lock_name, 5)"),
            {"lock_name": lock_name},
        )
        if acquired != 1:
            await db.rollback()
            raise ApiError(429, "register.code_rate_limited")

        try:
            await db.rollback()
            if await user_repository.get_by_email(db, email):
                await db.rollback()
                raise ApiError(409, "register.email_taken")

            now = datetime.now(UTC).replace(tzinfo=None)
            if await code_svc.is_within_cooldown(db, purpose="register", email=email, now=now):
                await db.rollback()
                raise ApiError(429, "register.code_rate_limited")

            record_id, raw_code = await code_svc.issue_code(
                db,
                purpose="register",
                email=email,
                now=now,
            )
            await db.commit()
        finally:
            await lock_conn.execute(text("SELECT RELEASE_LOCK(:lock_name)"), {"lock_name": lock_name})

    brand_name = await _brand_name(db)
    template = await load_template(db, "register_verify")
    subject, body = render_template_body(
        template,
        {
            "brand_name": brand_name,
            "email": email,
            "verification_code": raw_code,
        },
    )

    success, err = await send_email(
        db,
        recipient_email=email,
        subject=subject,
        main_content_raw=body,
        greeting="您好！",
        verification_code=raw_code,
    )
    if not success:
        await code_svc.delete_code(db, record_id)
        await db.commit()
        logger.error("Failed to send registration code email to %s: %s", email, err)
        raise ApiError(502, "register.email_send_failed")

    await log_manager_activity(
        db,
        actor="system",
        category="auth",
        operation=OperationResult(
            action="auth.register",
            phase="acceptance",
            outcome="success",
            target={"email": email},
        ),
        detail_key="register_code_sent",
        detail_params={"email": email},
    )

    return MessageResponse(message="验证码已发送，请查收邮件。")


@router.post("/register", response_model=RegisterResponse)
@limiter.limit("10/minute")
async def register(
    payload: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    if not await _allow_registration(db):
        raise ApiError(403, "register.disabled")

    email = normalize_email(payload.email)
    username = normalize_username(payload.username)
    raw_code = payload.code.strip()
    if not raw_code:
        raise ApiError(422, "register.invalid_code")

    try:
        agreements_items = await agreements_svc.validate_acceptance(
            db,
            payload.accepted_agreements,
            context="register",
        )
    except agreements_svc.AgreementError:
        raise ApiError(422, "register.agreement_required") from None

    if await user_repository.get_by_email(db, email):
        raise ApiError(409, "register.email_taken")
    if await user_repository.get_by_username(db, username):
        raise ApiError(409, "register.username_taken")

    now = datetime.now(UTC).replace(tzinfo=None)
    record, code_status = await code_svc.verify_latest_code(
        db,
        purpose="register",
        email=email,
        code=raw_code,
        now=now,
    )
    if code_status != "ok" or record is None:
        await db.rollback()
        raise ApiError(
            422,
            "register.code_expired" if code_status == "expired" else "register.invalid_code",
        )

    raw_hash = await asyncio.to_thread(PteroUser.hash_password_sync, payload.password)

    try:
        await code_svc.consume_code(db, record, now)
        created = await panel_db.create_user_with_hashed_password(
            db,
            username=username,
            email=email,
            first_name=(payload.first_name or username).strip(),
            last_name=(payload.last_name or "User").strip(),
            password_hash=raw_hash,
        )
        await db.commit()
    except panel_db.PanelDBError as exc:
        await db.rollback()
        if await user_repository.get_by_email(db, email):
            raise ApiError(409, "register.email_taken") from None
        if await user_repository.get_by_username(db, username):
            raise ApiError(409, "register.username_taken") from None
        logger.error("create_user (public register) failed for %s: %s", email, exc)
        raise ApiError(502, "register.create_failed") from exc

    await log_manager_activity(
        db,
        actor=created.username,
        category="auth",
        operation=OperationResult(
            action="auth.register",
            phase="execution",
            outcome="success",
            target={"user_id": created.id},
        ),
        detail_key="register_verified",
        detail_params={"username": created.username, "email": created.email},
    )

    # Best-effort agreement consent persistence.
    if agreements_items:
        try:
            fwd = request.headers.get("x-forwarded-for", "")
            request_ip: str | None = fwd.split(",")[0].strip() if fwd else None
            if request_ip is None and request.client is not None:
                request_ip = request.client.host
            await agreements_svc.record(
                db,
                user_id=int(created.id),
                items=agreements_items,
                context="register",
                ip=request_ip,
                locale=None,
                commit=False,
            )
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
            logger.exception("register: failed to record agreement acceptances for user=%s", created.id)

    # Best-effort referral row + invitee welcome coupon.
    from app.services.user import invite_codes as invite_svc

    raw_invite = (payload.invite_code or "").strip().upper() or None
    inviter_user_id: int | None = None
    if raw_invite:
        inviter_user_id = await invite_svc.resolve_active_inviter(db, raw_invite)

    if inviter_user_id and raw_invite:
        invitee_coupon = None
        try:
            from app.core.time import utc_naive_now as _now
            from app.db.models.billing import CouponTemplate
            from app.db.models.manager import UserReferral
            from app.services.billing import coupons as coupon_service

            referral = UserReferral(
                inviter_user_id=int(inviter_user_id),
                invitee_user_id=int(created.id),
                invite_code=raw_invite,
                status="registered",
                created_at=_now(),
            )
            db.add(referral)
            await db.flush()

            store = get_settings_store()
            enabled = bool(
                await store.get(
                    db,
                    "REFERRAL_REWARD_ENABLED",
                    BILLING_SPECS["REFERRAL_REWARD_ENABLED"].default_value(),
                )
            )
            if enabled:
                invitee_code = str(
                    await store.get(
                        db,
                        "REFERRAL_INVITEE_TEMPLATE_CODE",
                        BILLING_SPECS["REFERRAL_INVITEE_TEMPLATE_CODE"].default_value(),
                    )
                )
                tpl = (
                    await db.execute(
                        select(CouponTemplate).where(
                            CouponTemplate.code == invitee_code,
                            CouponTemplate.is_active.is_(True),
                        )
                    )
                ).scalar_one_or_none()
                if tpl is None:
                    logger.warning(
                        "register: invitee template %s missing; deferring coupon issuance to first-order grant",
                        invitee_code,
                    )
                else:
                    invitee_coupon = await coupon_service.issue_from_template(
                        db,
                        user_id=int(created.id),
                        template=tpl,
                        source="referral_invitee",
                        source_ref_id=referral.id,
                        commit=False,
                    )
                    referral.invitee_coupon_id = invitee_coupon.id
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
            logger.exception("register: failed to create UserReferral for invitee=%s", created.id)
            invitee_coupon = None

        if invitee_coupon is not None:
            try:
                from app.services.billing.referral_rewards import send_invitee_welcome_email

                await send_invitee_welcome_email(
                    db, invitee_user_id=int(created.id), coupon=invitee_coupon
                )
            except Exception:
                logger.exception("register: invitee welcome email failed (user=%s)", created.id)

    request.session.clear()
    request.session[SESSION_USER_ID_KEY] = int(created.id)

    return RegisterResponse(
        message="注册成功。",
        auto_login=True,
        username=created.username,
        is_admin=False,
    )


# ── Invite code probe ──

class InviteCheckResponse(BaseModel):
    valid: bool
    inviter_username: str | None = None


@router.get("/invite/check", response_model=InviteCheckResponse)
@limiter.limit("30/minute")
async def check_invite_code(
    request: Request,
    code: str,
    db: AsyncSession = Depends(get_db),
) -> InviteCheckResponse:
    """Lightweight probe used by the register page."""
    normalized = (code or "").strip().upper()
    if not normalized or len(normalized) != 8:
        return InviteCheckResponse(valid=False)
    from app.services.user import invite_codes as invite_svc

    user_id = await invite_svc.resolve_active_inviter(db, normalized)
    if not user_id:
        return InviteCheckResponse(valid=False)
    user = await user_repository.get_by_id(db, user_id)
    if user is None:
        return InviteCheckResponse(valid=False)
    return InviteCheckResponse(valid=True, inviter_username=user.username)
