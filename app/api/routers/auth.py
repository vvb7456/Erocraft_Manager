"""Authentication routers for the FastAPI backend."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.core.security import SESSION_USER_ID_KEY
from app.core.rate_limit import limiter
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
    username = "unknown"
    user_id = request.session.get(SESSION_USER_ID_KEY)
    if user_id:
        user = await user_repository.get_by_id(db, int(user_id))
        if user:
            username = user.username

    request.session.clear()
    await log_manager_activity(
        db,
        actor=username,
        category="auth",
        status="info",
        detail_key="logout",
        detail_params={"username": username},
    )
    return LogoutResponse(ok=True)
