"""Ownership dependencies for user-facing server routes."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.core.api_errors import ApiError
from app.db.models.pterodactyl import PteroServer, PteroUser
from app.db.repositories.servers import server_repository


async def get_owned_server(
    server_id: int = Path(...),
    current_user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PteroServer:
    server = await server_repository.get_by_id(db, server_id)
    # 统一返回 404，避免通过 403/404 差异枚举他人服务器 ID。
    if (
        server is None
        or (server.owner_id != current_user.id and not current_user.root_admin)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="服务器不存在")
    return server


async def get_active_owned_server(
    server: PteroServer = Depends(get_owned_server),
) -> PteroServer:
    if server.is_suspended:
        raise ApiError(403, "server.suspended")
    return server
