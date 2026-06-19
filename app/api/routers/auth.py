"""Authentication routers for the FastAPI backend."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.api.routers.public import REGISTER_TOKEN_EXPIRY_MINUTES
from app.core.security import SESSION_USER_ID_KEY
from app.core.rate_limit import limiter
from app.core.time import utc_naive_now
from app.db.models.manager import ManagerPendingRegistration
from app.db.models.pterodactyl import PteroUser
from app.db.repositories.users import user_repository
from app.schemas.auth import LoginRequest, LoginResponse, LogoutResponse, MeResponse
from app.services.audit import log_manager_activity
from app.services.pterodactyl_activity import get_request_ip, pterodactyl_activity_logger

router = APIRouter(tags=["auth"])


@router.post("/login", response_model=LoginResponse)
@limiter.limit("10/minute")
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    username = payload.username.strip()
    password = payload.password
    if not username or not password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="auth.credentials_required")

    user = await user_repository.get_by_username_or_email(db, username)
    if not user or not user.check_password(password):
        # If the user can't be found at all, check whether they're just
        # awaiting email verification. Pending registrations live in
        # ``manager_pending_registrations`` and only become real ``PteroUser``
        # rows after the verification link is clicked, so a freshly-registered
        # but unverified user would otherwise be told "invalid credentials".
        if not user:
            pending = (
                await db.execute(
                    select(ManagerPendingRegistration)
                    .where(
                        ManagerPendingRegistration.used_at.is_(None),
                        or_(
                            ManagerPendingRegistration.email == username.lower(),
                            ManagerPendingRegistration.username == username,
                        ),
                    )
                    .order_by(ManagerPendingRegistration.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if pending is not None and pending.created_at is not None:
                if utc_naive_now() - pending.created_at <= timedelta(
                    minutes=REGISTER_TOKEN_EXPIRY_MINUTES
                ):
                    await log_manager_activity(
                        db,
                        actor="system",
                        category="auth",
                        status="info",
                        detail_key="login.email_not_verified",
                        detail_params={
                            "username": username,
                            "email": pending.email,
                        },
                    )
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="auth.email_not_verified",
                    )

        if user:
            await pterodactyl_activity_logger.log_account_activity(
                db,
                user=user,
                actor=None,
                event="auth:fail",
                properties={
                    "username": username,
                    "ip": get_request_ip(request),
                    "useragent": request.headers.get("user-agent"),
                },
                request=request,
            )
            await db.commit()
        # When the user doesn't exist, fall back to ``system`` (the attempted
        # username is preserved in detail_params for forensics). When the user
        # exists but the password is wrong, attribute the failure to them.
        await log_manager_activity(
            db,
            actor=user.username if user else "system",
            category="auth",
            status="failure",
            detail_key="login_failed",
            detail_params={"username": username},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth.invalid_credentials")

    request.session.clear()
    request.session[SESSION_USER_ID_KEY] = int(user.id)

    await pterodactyl_activity_logger.log_account_activity(
        db,
        user=user,
        actor=user,
        event="auth:success",
        properties={
            "ip": get_request_ip(request),
            "useragent": request.headers.get("user-agent"),
        },
        request=request,
    )
    await db.commit()

    await log_manager_activity(
        db,
        actor=user.username,
        category="auth",
        status="success",
        detail_key="login_success",
        detail_params={"username": user.username},
    )
    return LoginResponse(
        ok=True,
        username=user.username,
        is_admin=bool(user.root_admin),
        language=user.language or "zh",
    )


@router.get("/me", response_model=MeResponse)
async def me(
    current_user: PteroUser = Depends(get_current_user),
) -> MeResponse:
    return MeResponse(
        ok=True,
        username=current_user.username,
        is_admin=bool(current_user.root_admin),
        language=current_user.language or "zh",
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> LogoutResponse:
    user_id = request.session.get(SESSION_USER_ID_KEY)
    username = "unknown"
    if user_id:
        user = await user_repository.get_by_id(db, int(user_id))
        if user:
            username = user.username

    request.session.clear()

    # Only write an audit row when there was an authenticated session.
    # The logout endpoint is unauthenticated (no get_current_user dep) so
    # web crawlers/scanners that probe POST /api/logout would otherwise
    # pollute the audit trail with "unknown" actor entries and trigger
    # pointless DB writes. A session-less logout is a no-op (clearing an
    # already-empty session), so there is nothing meaningful to audit.
    if user_id:
        await log_manager_activity(
            db,
            actor=username,
            category="auth",
            status="info",
            detail_key="logout",
            detail_params={"username": username},
        )
    return LogoutResponse(ok=True)
