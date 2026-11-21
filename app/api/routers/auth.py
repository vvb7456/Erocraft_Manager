"""Authentication routers for the FastAPI backend."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.core.api_errors import ApiError
from app.core.contracts import OperationResult
from app.core.rate_limit import limiter
from app.core.security import SESSION_USER_ID_KEY
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
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, "auth.credentials_required")

    user = await user_repository.get_by_username_or_email(db, username)
    valid_password = (
        user is not None
        and len(password.encode("utf-8")) <= 72
        and await asyncio.to_thread(user.check_password, password)
    )
    if not user or not valid_password:
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
        await log_manager_activity(
            db,
            actor=user.username if user else "system",
            category="auth",
            operation=OperationResult(action="auth.login", phase="request", outcome="failed", target={"username": username}),
            detail_key="login_failed",
            detail_params={"username": username},
        )
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "auth.invalid_credentials")

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
        operation=OperationResult(action="auth.login", phase="execution", outcome="success", target={"user_id": user.id}),
        detail_key="login_success",
        detail_params={"username": user.username},
    )
    return LoginResponse(
        ok=True,
        username=user.username,
        is_admin=bool(user.root_admin),
        has_owned_server=bool(user.has_owned_server),
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
        has_owned_server=bool(current_user.has_owned_server),
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

    if user_id:
        await log_manager_activity(
            db,
            actor=username,
            category="auth",
            operation=OperationResult(action="auth.logout", phase="execution", outcome="success", target={"username": username}),
            detail_key="logout",
            detail_params={"username": username},
        )
    return LogoutResponse(ok=True)
