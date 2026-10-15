"""Authentication dependencies for FastAPI routes."""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.db import get_db
from app.core.security import SESSION_USER_ID_KEY
from app.core.api_errors import ApiError
from app.db.models.pterodactyl import PteroUser
from app.db.repositories.users import user_repository


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PteroUser:
    user_id = request.session.get(SESSION_USER_ID_KEY)
    if not user_id:
        raise ApiError(401, "auth.session_required")

    user = await user_repository.get_by_id(db, int(user_id))
    if not user:
        request.session.clear()
        raise ApiError(401, "auth.session_required")

    return user


async def require_admin(
    current_user: PteroUser = Depends(get_current_user),
) -> PteroUser:
    if not current_user.root_admin:
        raise ApiError(403, "auth.forbidden")
    return current_user
