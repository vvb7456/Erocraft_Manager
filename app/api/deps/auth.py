"""Authentication dependencies for FastAPI routes."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.db import get_db
from app.core.security import SESSION_USER_ID_KEY
from app.db.models.pterodactyl import PteroUser
from app.db.repositories.users import user_repository


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PteroUser:
    user_id = request.session.get(SESSION_USER_ID_KEY)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    user = await user_repository.get_by_id(db, int(user_id))
    if not user:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    return user


async def require_admin(
    current_user: PteroUser = Depends(get_current_user),
) -> PteroUser:
    if not current_user.root_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return current_user
