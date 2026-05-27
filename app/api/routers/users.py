"""Admin user management routes."""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.runtime_settings import SETTINGS_SPECS
from app.core.settings_store import get_settings_store
from app.core.tokens import hash_token_async
from app.db.models import PteroServer, PteroUser
from app.db.models.manager import ManagerPasswordReset
from app.db.repositories.users import user_repository
from app.schemas.users import (
    BatchUsersRequest,
    BatchUsersResponse,
    CreateUserRequest,
    CreateUserResponse,
    UpdateUserRequest,
    UserListItem,
    UserMessageResponse,
    UserRef,
    UsersListResponse,
)
from app.services.audit import log_manager_activity
from app.services.email import (
    EmailClient,
    generate_temporary_password,
    get_email_delay,
    get_site_url,
    get_smtp_config,
    load_template,
    render_template_body,
    send_email,
)
from app.services import server_lifecycle
from app.services.server_lifecycle import LifecycleError

router = APIRouter(prefix="/admin", tags=["users"])
logger = logging.getLogger(__name__)

_USERNAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _validate_username(username: str) -> None:
    if not _USERNAME_RE.match(username):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="用户名只能包含小写字母、数字和连字符，且必须以字母或数字开头和结尾",
        )


async def _brand_name(db: AsyncSession) -> str:
    return str(
        await get_settings_store().get(
            db,
            "BRAND_NAME",
            SETTINGS_SPECS["BRAND_NAME"].default_value(),
        )
    )


async def _create_password_reset_token(db: AsyncSession, user_id: int) -> str:
    raw_token = secrets.token_hex(32)
    token_hash = await hash_token_async(raw_token)
    # Invalidate prior unused tokens
    await db.execute(
        update(ManagerPasswordReset)
        .where(ManagerPasswordReset.user_id == user_id)
        .where(ManagerPasswordReset.used_at.is_(None))
        .values(used_at=_utc_now())
    )
    db.add(ManagerPasswordReset(
        user_id=user_id,
        token=token_hash,
    ))
    return raw_token


async def _delete_user_remote(db: AsyncSession, user_id: int) -> int:
    server_rows = await db.execute(
        select(PteroServer.id)
        .where(PteroServer.owner_id == user_id)
        .order_by(PteroServer.id.asc())
    )
    server_ids = [int(server_id) for server_id in server_rows.scalars().all()]
    await db.commit()

    deleted = 0
    for server_id in server_ids:
        await server_lifecycle.delete_server(db, server_id)
        deleted += 1
    try:
        await server_lifecycle.delete_user(db, user_id)
    except LifecycleError as exc:
        # Servers were deleted (each delete_server commits internally) but the
        # user row could not be removed — most likely a transient DB issue.
        # Log the partial state explicitly so an operator knows that retrying
        # `DELETE /users/{id}` is safe (the server-deletion loop is now empty
        # and only the user row needs to go). Without this log, the original
        # 502 looks identical to "operation didn't start" and the user row
        # silently leaks. (Audit H3.)
        try:
            await log_manager_activity(
                db,
                actor="system",
                category="user",
                status="failure",
                detail_key="delete_user_partial",
                detail_params={
                    "user_id": user_id,
                    "deleted_server_count": deleted,
                    "error": str(exc)[:200],
                },
            )
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
        raise
    await db.commit()
    return deleted


@router.get("/users", response_model=UsersListResponse)
async def list_users(
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UsersListResponse:
    rows = await user_repository.list_for_admin(db)
    return UsersListResponse(
        users=[
            UserListItem(
                id=user.id,
                uuid=user.uuid,
                username=user.username,
                email=user.email,
                first_name=user.name_first,
                last_name=user.name_last,
                root_admin=bool(user.root_admin),
                language=user.language,
                created_at=user.created_at.isoformat() if user.created_at else None,
                updated_at=user.updated_at.isoformat() if user.updated_at else None,
                server_count=server_count,
                inviter_user_id=inviter_id,
                inviter_username=inviter_username,
            )
            for user, server_count, inviter_id, inviter_username in rows
        ]
    )


@router.post("/users", response_model=CreateUserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: CreateUserRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CreateUserResponse:
    email = payload.email.strip()
    username = payload.username.strip()
    if not email or not username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邮箱和用户名不能为空")
    _validate_username(username)

    if await user_repository.get_by_email(db, email):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"邮箱 {email} 已存在")
    if await user_repository.get_by_username(db, username):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"用户名 {username} 已存在")

    first_name = payload.firstName.strip() or username
    last_name = payload.lastName.strip() or "User"
    temporary_password = generate_temporary_password()
    await db.commit()

    try:
        created = await server_lifecycle.create_user(
            db,
            email=email,
            username=username,
            first_name=first_name,
            last_name=last_name,
            password=temporary_password,
        )
        await db.commit()
    except LifecycleError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    user_id = created.id

    # Cache ORM field before potential flush/rollback boundary
    admin_username = current_user.username

    email_sent: bool | None = None
    if payload.sendWelcome:
        store = get_settings_store()
        site_url = await get_site_url(db)
        try:
            token = await _create_password_reset_token(db, int(user_id))
            await db.flush()
        except Exception as exc:
            await db.rollback()
            cleanup_succeeded = False
            try:
                await server_lifecycle.delete_user(db, int(user_id))
                await db.commit()
                cleanup_succeeded = True
            except LifecycleError:
                await db.rollback()
                logger.exception("Failed to delete user %s after password reset token creation failed", user_id)

            logger.exception("Failed to persist password reset token for user %s", user_id)
            detail = "用户已创建，但密码重置令牌写入失败"
            if cleanup_succeeded:
                detail += "，已自动回滚"
            else:
                detail += "，且自动回滚失败，请检查面板状态"
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail) from exc

        template = await load_template(db, "create_user")
        brand_name = await _brand_name(db)
        reset_url = f"{site_url}/#/reset-password?token={token}&email={email}"
        subject, body = render_template_body(
            template,
            {
                "brand_name": brand_name,
                "username": username,
                "email": email,
                "password": temporary_password,
                "reset_url": reset_url,
            },
        )
        email_sent, _ = await send_email(
            db,
            recipient_email=email,
            subject=subject,
            main_content_raw=body,
            greeting=f"你好, {first_name}!",
            action_text="设置您的账户密码",
            action_url=reset_url,
        )

        if email_sent:
            await db.commit()
        else:
            await db.rollback()

    await log_manager_activity(
        db,
        actor=admin_username,
        category="user",
        status="success",
        detail_key="create_user",
        detail_params={"username": username, "email": email},
    )
    return CreateUserResponse(
        message=f"用户 '{username}' 创建成功",
        emailSent=email_sent,
        user=UserRef(id=int(user_id), username=created.username),
    )


@router.put("/users/{user_id}", response_model=UserMessageResponse)
async def update_user(
    user_id: int,
    payload: UpdateUserRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserMessageResponse:
    user = await user_repository.get_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    username = payload.username.strip()
    email = payload.email.strip()
    if not email or not username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邮箱和用户名不能为空")
    _validate_username(username)

    existing_email = await user_repository.get_by_email(db, email)
    if existing_email and existing_email.id != user_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"邮箱 {email} 已存在")
    existing_username = await user_repository.get_by_username(db, username)
    if existing_username and existing_username.id != user_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"用户名 {username} 已存在")

    await db.commit()
    try:
        await server_lifecycle.update_user(
            db,
            user_id,
            email=email,
            username=username,
            first_name=payload.firstName.strip() or user.name_first or username,
            last_name=payload.lastName.strip() or user.name_last or "User",
            password=payload.password.strip() if payload.password else None,
            language=(payload.language.strip() if payload.language else None) or None,
        )
        await db.commit()
    except LifecycleError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if payload.password:
        await db.execute(
            update(ManagerPasswordReset)
            .where(ManagerPasswordReset.user_id == user_id)
            .where(ManagerPasswordReset.used_at.is_(None))
            .values(used_at=_utc_now())
        )
        await db.commit()

    await log_manager_activity(
        db,
        actor=current_user.username,
        category="user",
        status="success",
        detail_key="edit_user",
        detail_params={"user_id": user_id},
    )
    return UserMessageResponse(message="用户已更新")


@router.delete("/users/{user_id}", response_model=UserMessageResponse)
async def delete_user(
    user_id: int,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserMessageResponse:
    user = await user_repository.get_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    try:
        deleted_server_count = await _delete_user_remote(db, user_id)
    except LifecycleError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await log_manager_activity(
        db,
        actor=current_user.username,
        category="user",
        status="success",
        detail_key="delete_user",
        detail_params={"user_id": user_id, "server_count": deleted_server_count},
    )
    return UserMessageResponse(message=f"用户及其 {deleted_server_count} 台服务器已删除")


@router.post("/users/batch", response_model=BatchUsersResponse)
async def batch_users(
    payload: BatchUsersRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BatchUsersResponse:
    success = 0
    errors = 0

    if payload.action == "email":
        users = await user_repository.list_by_ids(db, payload.userIds)
        template = await load_template(db, "bulk")
        brand_name = await _brand_name(db)
        site_url = await get_site_url(db)
        delay = await get_email_delay(db)
        cfg = await get_smtp_config(db)
        await db.commit()

        async with EmailClient(
            cfg, site_url, db=db,
            actor=current_user.username, log_category="user",
        ) as client:
            for index, user in enumerate(users):
                if not user.email:
                    errors += 1
                    continue

                subject, body = render_template_body(
                    template,
                    {
                        "brand_name": brand_name,
                        "username": user.username,
                        "email": user.email,
                        "server_name": "(不适用)",
                        "server_id": "(不适用)",
                        "expiration_date": "(不适用)",
                    },
                )
                sent, _ = await client.send(
                    recipient_email=user.email,
                    subject=subject,
                    main_content_raw=body,
                    greeting=f"您好, {user.username}!",
                    action_text="登录系统查看",
                    action_url=site_url,
                )
                if sent:
                    success += 1
                else:
                    errors += 1
                if delay > 0 and index < len(users) - 1:
                    await asyncio.sleep(delay)

        await log_manager_activity(
            db,
            actor=current_user.username,
            category="user",
            status="failure" if errors else "success",
            detail_key="batch_email_users",
            detail_params={"success": success, "failed": errors},
        )
    else:
        for user_id in payload.userIds:
            try:
                await _delete_user_remote(db, user_id)
                success += 1
            except LifecycleError:
                await db.rollback()
                errors += 1

        await log_manager_activity(
            db,
            actor=current_user.username,
            category="user",
            status="failure" if errors else "success",
            detail_key="batch_delete_users",
            detail_params={"success": success, "failed": errors},
        )

    return BatchUsersResponse(
        message=f"操作完成：成功 {success}，失败 {errors}",
        success=success,
        failed=errors,
    )
