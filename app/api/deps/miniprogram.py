"""Bearer credentials accepted only by the mini-program router."""

import hashlib

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.db import get_db
from app.core.api_errors import ApiError
from app.core.settings_store import get_settings_store
from app.core.time import utc_naive_now
from app.db.models.miniprogram import MiniProgramBinding, MiniProgramSession
from app.db.models.pterodactyl import PteroUser

bearer = HTTPBearer(auto_error=False)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_required() -> ApiError:
    return ApiError(401, "auth.session_required", headers={"WWW-Authenticate": "Bearer"})


async def get_mini_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> MiniProgramSession:
    if credentials is None:
        raise session_required()
    session = await db.get(MiniProgramSession, token_hash(credentials.credentials))
    appid = await get_settings_store().get(db, "WECHAT_PAY_MINIPROGRAM_APPID", "")
    if session is None or session.expires_at <= utc_naive_now() or session.appid != appid:
        raise session_required()
    return session


async def get_mini_user(
    session: MiniProgramSession = Depends(get_mini_session),
    db: AsyncSession = Depends(get_db),
) -> PteroUser:
    if session.binding_id is None:
        raise ApiError(403, "miniprogram.binding_required")
    binding = await db.get(MiniProgramBinding, session.binding_id)
    if binding is None:
        raise session_required()
    user = await db.get(PteroUser, binding.user_id)
    if user is None:
        raise session_required()
    return user
