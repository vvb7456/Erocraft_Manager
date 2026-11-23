"""Authentication dependencies for FastAPI routes."""

from __future__ import annotations

import logging

from fastapi import Depends, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.db import get_db
from app.core.api_errors import ApiError
from app.core.config import get_settings
from app.core.security import (
    SESSION_AUTH_FINGERPRINT_KEY,
    SESSION_USER_ID_KEY,
    verify_session_fingerprint,
)
from app.db.models.miniprogram import MiniProgramBinding, MiniProgramSession
from app.db.models.pterodactyl import PanelNode, PteroServer, PteroUser
from app.db.repositories.servers import exclude_placeholders
from app.db.repositories.users import user_repository
from app.services.wings import WingsServiceError, wings_service

logger = logging.getLogger(__name__)


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PteroUser:
    user_id = request.session.get(SESSION_USER_ID_KEY)
    if not user_id:
        raise ApiError(401, "auth.session_required")

    user = await user_repository.get_by_id(db, int(user_id))
    if not user or not verify_session_fingerprint(
        request.session.get(SESSION_AUTH_FINGERPRINT_KEY),
        user.password,
        get_settings().secret_key,
    ):
        request.session.clear()
        raise ApiError(401, "auth.session_required")

    return user


async def revoke_user_external_sessions(
    db: AsyncSession,
    user_id: int,
    *,
    user_uuid: str | None = None,
    is_admin: bool = False,
) -> None:
    """Revoke mini-program sessions/bindings and active Wings JWTs after a password change."""
    binding_ids = list(
        (
            await db.scalars(
                select(MiniProgramBinding.id).where(MiniProgramBinding.user_id == user_id)
            )
        ).all()
    )
    if binding_ids:
        await db.execute(
            delete(MiniProgramSession).where(MiniProgramSession.binding_id.in_(binding_ids))
        )
        await db.execute(
            delete(MiniProgramBinding).where(MiniProgramBinding.id.in_(binding_ids))
        )

    if not user_uuid:
        return
    if is_admin:
        # 管理员可在所有节点签发客户服务器的 Wings 令牌，改密时须向全部节点撤销。
        node_ids = list((await db.scalars(select(PanelNode.id))).all())
    else:
        node_ids = list(
            (
                await db.scalars(
                    select(PteroServer.node_id)
                    .where(PteroServer.owner_id == user_id, exclude_placeholders())
                    .distinct()
                )
            ).all()
        )
    for node_id in node_ids:
        try:
            await wings_service.deauthorize_user(db, int(node_id), user_uuid)
        except WingsServiceError as exc:
            logger.warning(
                "Failed to deauthorize Wings sessions for user=%s node=%s: %s",
                user_id,
                node_id,
                exc,
            )


async def require_admin(
    current_user: PteroUser = Depends(get_current_user),
) -> PteroUser:
    if not current_user.root_admin:
        raise ApiError(403, "auth.forbidden")
    return current_user
