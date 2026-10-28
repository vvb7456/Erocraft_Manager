"""按账号隔离的客服聊天，实时提醒由单个 Web 进程推送。"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.deps.auth import require_admin
from app.api.deps.support import SupportUser, get_support_user
from app.api.deps.db import get_db
from app.core.runtime_settings import SETTINGS_SPECS
from app.core.settings_store import get_settings_store
from app.core.time import to_iso_z, utc_naive_now
from app.db.models.pterodactyl import PteroServer, PteroUser
from app.db.models.support import SupportConversation, SupportMessage
from app.db.repositories.servers import exclude_placeholders
from app.services import support_images

router = APIRouter(prefix="/support", tags=["support"])
_MAX_IMAGE = 4 * 1024 * 1024
_listeners: set[tuple[int, bool, asyncio.Event]] = set()


def notify_change(user_id: int) -> None:
    for uid, admin, event in _listeners:
        if admin or uid == user_id:
            event.set()


class MessageInput(BaseModel):
    content: str = Field(default="", max_length=4000)
    client_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{16,64}$")


class ReadInput(BaseModel):
    message_id: int = Field(ge=0)


def message_out(message: SupportMessage) -> dict:
    return {
        "id": message.id,
        "client_id": message.client_id,
        "content": message.content,
        "is_admin": message.is_admin,
        "automated": message.sender_id == 0,
        "created_at": to_iso_z(message.created_at),
        "image_url": f"/api/support/messages/{message.id}/image" if message.image_type else None,
    }


async def conversation(db: AsyncSession, cid: int, user: SupportUser, *, lock: bool = False) -> SupportConversation:
    stmt = select(SupportConversation).where(SupportConversation.id == cid)
    if not user.root_admin:
        stmt = stmt.where(SupportConversation.user_id == user.id)
    if lock:
        stmt = stmt.with_for_update()
    row = await db.scalar(stmt)
    if row is None:
        raise HTTPException(404, "会话不存在")
    return row


@router.post("/conversation")
async def my_conversation(user: SupportUser = Depends(get_support_user), db: AsyncSession = Depends(get_db)) -> dict:
    uid = user.id
    row = await db.scalar(select(SupportConversation).where(SupportConversation.user_id == uid))
    if row is None:
        keys = ("SUPPORT_WELCOME_ENABLED", "SUPPORT_WELCOME_MESSAGE")
        settings = await get_settings_store().get_many(db, {key: SETTINGS_SPECS[key].default_value() for key in keys})
        try:
            row = SupportConversation(user_id=uid)
            db.add(row)
            await db.flush()
            welcome = str(settings["SUPPORT_WELCOME_MESSAGE"] or "").strip()[:2000]
            if settings["SUPPORT_WELCOME_ENABLED"] and welcome and not user.root_admin:
                # Zero is reserved for automated messages; panel user IDs are positive.
                message = SupportMessage(conversation_id=row.id, sender_id=0, is_admin=True,
                                         client_id="welcome_message_v1", content=welcome)
                db.add(message)
                await db.flush()
                row.last_message_id = message.id
                row.updated_at = message.created_at
            await db.commit()
            notify_change(uid)
        except IntegrityError:
            await db.rollback()
            row = await db.scalar(select(SupportConversation).where(SupportConversation.user_id == uid))
    assert row is not None
    return {"id": row.id, "user_read_id": row.user_read_id, "admin_read_id": row.admin_read_id}


@router.get("/unread")
async def unread_count(user: SupportUser = Depends(get_support_user), db: AsyncSession = Depends(get_db)) -> dict:
    read_id = SupportConversation.admin_read_id if user.root_admin else SupportConversation.user_read_id
    # Arrival tracking is independent of read receipts, which can advance before the sound check.
    stmt = select(
        func.count(case((SupportMessage.id > read_id, SupportMessage.id))),
        func.max(case((SupportMessage.sender_id != 0, SupportMessage.id))),
    ).join(SupportConversation, SupportConversation.id == SupportMessage.conversation_id)
    if user.root_admin:
        stmt = stmt.where(SupportMessage.is_admin.is_(False))
    else:
        stmt = stmt.where(SupportConversation.user_id == user.id, SupportMessage.is_admin.is_(True))
    unread, latest_incoming_id = (await db.execute(stmt)).one()
    return {"unread": unread, "latest_incoming_id": latest_incoming_id or 0}


@router.get("/conversations")
async def list_conversations(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    q: str = Query("", max_length=100),
    unread_only: bool = False,
    category: Literal["all", "pre_sales", "after_sales"] = "all",
    conversation_id: int | None = Query(None, gt=0),
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    unread = select(func.count(SupportMessage.id)).where(
        SupportMessage.conversation_id == SupportConversation.id,
        SupportMessage.id > SupportConversation.admin_read_id,
        SupportMessage.is_admin.is_(False),
    ).correlate(SupportConversation).scalar_subquery()
    # Ownership is current, not the permanent trial-eligibility flag; expired servers still count.
    has_server = select(PteroServer.id).where(
        PteroServer.owner_id == SupportConversation.user_id,
        exclude_placeholders(),
    ).correlate(SupportConversation).exists()
    stmt = (
        select(SupportConversation, PteroUser.username, unread, SupportMessage.content, SupportMessage.image_type, has_server)
        .join(PteroUser, PteroUser.id == SupportConversation.user_id)
        .outerjoin(SupportMessage, SupportMessage.id == SupportConversation.last_message_id)
        .where(SupportConversation.last_message_id > 0)
        .where(select(SupportMessage.id).where(
            SupportMessage.conversation_id == SupportConversation.id,
            SupportMessage.is_admin.is_(False),
        ).correlate(SupportConversation).exists())
        .order_by(SupportConversation.updated_at.desc(), SupportConversation.id.desc())
    )
    if q.strip():
        stmt = stmt.where(PteroUser.username.contains(q.strip(), autoescape=True))
    if conversation_id is not None:
        stmt = stmt.where(SupportConversation.id == conversation_id)
    if unread_only:
        stmt = stmt.where(unread > 0)
    if category == "pre_sales":
        stmt = stmt.where(~has_server)
    elif category == "after_sales":
        stmt = stmt.where(has_server)
    rows = (await db.execute(stmt.offset(offset).limit(limit + 1))).all()
    return {"has_more": len(rows) > limit, "items": [
        {"id": c.id, "username": name, "user_id": c.user_id, "unread": count,
         "preview": (text or "")[:100], "has_image": bool(image), "updated_at": to_iso_z(c.updated_at),
         "category": "after_sales" if owns_server else "pre_sales"}
        for c, name, count, text, image, owns_server in rows[:limit]
    ]}


@router.get("/conversations/{cid}/messages")
async def messages(
    cid: int, after: int = Query(0, ge=0), before: int = Query(0, ge=0),
    user: SupportUser = Depends(get_support_user), db: AsyncSession = Depends(get_db),
) -> dict:
    row = await conversation(db, cid, user)
    stmt = select(SupportMessage).where(SupportMessage.conversation_id == cid)
    if after:
        stmt = stmt.where(SupportMessage.id > after).order_by(SupportMessage.id)
    else:
        if before:
            stmt = stmt.where(SupportMessage.id < before)
        stmt = stmt.order_by(SupportMessage.id.desc())
    found = list((await db.scalars(stmt.limit(51))).all())
    more = len(found) > 50
    found = found[:50]
    if not after:
        found.reverse()
    return {"items": [message_out(m) for m in found], "has_more": more,
            "user_read_id": row.user_read_id, "admin_read_id": row.admin_read_id}


@router.post("/conversations/{cid}/messages")
async def send_message(cid: int, request: Request, user: SupportUser = Depends(get_support_user), db: AsyncSession = Depends(get_db)) -> dict:
    await conversation(db, cid, user)
    await db.commit()
    image_data = None
    image_type = None
    try:
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            async with request.form(max_files=1, max_fields=2, max_part_size=16_384) as form:
                payload = MessageInput(content=form.get("content", ""), client_id=form.get("client_id"))
                upload = form.get("image")
                if isinstance(upload, UploadFile):
                    data = await upload.read(_MAX_IMAGE + 1)
                    if len(data) > _MAX_IMAGE:
                        raise HTTPException(413, "截图不能超过4MB")
                    image_type = support_images.image_type(data)
                    image_data = data
        else:
            if len(await request.body()) > 20_000:
                raise HTTPException(413, "消息过长")
            payload = MessageInput.model_validate(await request.json())
    except (ValidationError, ValueError, TypeError) as exc:
        raise HTTPException(400, "消息格式不正确") from exc
    content = payload.content.strip()
    if not content and not image_data:
        raise HTTPException(400, "请输入消息或选择截图")
    row = await conversation(db, cid, user, lock=True)
    existing = await db.scalar(select(SupportMessage).where(
        SupportMessage.conversation_id == cid, SupportMessage.sender_id == user.id,
        SupportMessage.client_id == payload.client_id,
    ))
    if existing:
        return message_out(existing)
    count = await db.scalar(select(func.count()).select_from(SupportMessage).where(
        SupportMessage.conversation_id == cid, SupportMessage.sender_id == user.id,
        SupportMessage.created_at > utc_naive_now() - timedelta(minutes=1),
    ))
    if count and count >= 30:
        raise HTTPException(429, "发送过于频繁，请稍后重试")
    image_path = await run_in_threadpool(support_images.save_image, image_data, image_type) if image_data and image_type else None
    message = SupportMessage(
        conversation_id=cid, sender_id=user.id, is_admin=bool(user.root_admin),
        client_id=payload.client_id, content=content, image_path=image_path, image_type=image_type,
    )
    db.add(message)
    await db.flush()
    row.last_message_id = message.id
    row.updated_at = message.created_at
    if not user.root_admin:
        from app.services.notifications.events import support_message

        await support_message(db, conversation_id=cid, message_id=message.id, username=user.username)
    await db.commit()
    notify_change(row.user_id)
    return message_out(message)


@router.post("/conversations/{cid}/read")
async def mark_read(cid: int, payload: ReadInput, user: SupportUser = Depends(get_support_user), db: AsyncSession = Depends(get_db)) -> dict:
    row = await conversation(db, cid, user)
    cursor = min(payload.message_id, row.last_message_id)
    column = SupportConversation.admin_read_id if user.root_admin else SupportConversation.user_read_id
    changed = cursor > (row.admin_read_id if user.root_admin else row.user_read_id)
    await db.execute(update(SupportConversation).where(SupportConversation.id == cid, column < cursor).values({column.key: cursor}))
    await db.commit()
    if changed:
        notify_change(row.user_id)
    return {"ok": True}


@router.get("/messages/{mid}/image")
async def image(mid: int, user: SupportUser = Depends(get_support_user), db: AsyncSession = Depends(get_db)) -> FileResponse:
    message = await db.get(SupportMessage, mid)
    if message is None or not message.image_path:
        raise HTTPException(404, "截图不存在")
    await conversation(db, message.conversation_id, user)
    path = support_images.image_path(message.image_path)
    if not path.is_file():
        raise HTTPException(410, "截图已清理")
    return FileResponse(path, media_type=message.image_type, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/events")
async def events(request: Request, user: SupportUser = Depends(get_support_user), db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    uid, admin = user.id, bool(user.root_admin)
    await db.commit()

    async def stream():
        changed = asyncio.Event()
        listener = (uid, admin, changed)
        _listeners.add(listener)
        try:
            yield "retry: 2000\n\nevent: change\ndata: {}\n\n"
            # 每十分钟重连，经正常请求认证重新核对登录身份。
            until = asyncio.get_running_loop().time() + 600
            while asyncio.get_running_loop().time() < until:
                if await request.is_disconnected():
                    return
                try:
                    await asyncio.wait_for(changed.wait(), timeout=15)
                    changed.clear()
                    yield "event: change\ndata: {}\n\n"
                except TimeoutError:
                    yield "event: heartbeat\ndata: {}\n\n"
        finally:
            _listeners.discard(listener)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
