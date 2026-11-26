"""User write primitives (flush-only; callers own ``db.commit()``)."""

from __future__ import annotations

import asyncio
import uuid as _uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_naive_now_sec
from app.db.models.pterodactyl import PteroUser


class UserServiceError(RuntimeError):
    pass


class UserNotFoundError(UserServiceError):
    pass


class UserConflictError(UserServiceError):
    pass


@dataclass(slots=True, frozen=True)
class CreatedUser:
    id: int
    uuid: str
    username: str
    email: str


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    email: str,
    first_name: str,
    last_name: str,
    password: str,
    root_admin: bool = False,
    language: str = "zh",
) -> CreatedUser:
    password_hash = await asyncio.to_thread(PteroUser.hash_password_sync, password)
    return await create_user_with_hashed_password(
        db,
        username=username,
        email=email,
        first_name=first_name,
        last_name=last_name,
        password_hash=password_hash,
        root_admin=root_admin,
        language=language,
    )


async def create_user_with_hashed_password(
    db: AsyncSession,
    *,
    username: str,
    email: str,
    first_name: str,
    last_name: str,
    password_hash: str,
    root_admin: bool = False,
    language: str = "zh",
) -> CreatedUser:
    now = utc_naive_now_sec()
    user = PteroUser(
        uuid=str(_uuid.uuid4()),
        username=username,
        email=email,
        name_first=first_name,
        name_last=last_name,
        language=language,
        root_admin=root_admin,
        use_totp=False,
        gravatar=True,
        created_at=now,
        updated_at=now,
    )
    user.password = password_hash
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise UserConflictError(f"用户创建失败（用户名或邮箱冲突）: {exc.orig}") from exc
    return CreatedUser(id=int(user.id), uuid=user.uuid, username=user.username, email=user.email)


async def update_user(
    db: AsyncSession,
    user_id: int,
    *,
    email: str,
    username: str,
    first_name: str,
    last_name: str,
    password: str | None = None,
    language: str | None = None,
    root_admin: bool | None = None,
) -> None:
    user = await db.get(PteroUser, user_id)
    if user is None:
        raise UserNotFoundError(f"用户 {user_id} 不存在")
    user.email = email
    user.username = username
    user.name_first = first_name
    user.name_last = last_name
    if password:
        user.password = await asyncio.to_thread(PteroUser.hash_password_sync, password)
    if language is not None:
        user.language = language
    if root_admin is not None:
        user.root_admin = bool(root_admin)
    user.updated_at = utc_naive_now_sec()
    try:
        await db.flush()
    except IntegrityError as exc:
        raise UserConflictError(f"用户更新失败（用户名或邮箱冲突）: {exc.orig}") from exc


async def delete_user(db: AsyncSession, user_id: int) -> None:
    user = await db.get(PteroUser, user_id)
    if user is None:
        return
    await db.delete(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise UserConflictError(f"删除用户 {user_id} 失败（请先删除其名下服务器）: {exc.orig}") from exc


async def mark_user_owned_server(db: AsyncSession, user_id: int) -> bool:
    user = await db.get(PteroUser, user_id)
    if user is None or user.has_owned_server:
        return False
    user.has_owned_server = True
    await db.flush()
    return True


__all__ = [
    "UserServiceError",
    "UserNotFoundError",
    "UserConflictError",
    "CreatedUser",
    "create_user",
    "create_user_with_hashed_password",
    "update_user",
    "delete_user",
    "mark_user_owned_server",
]
