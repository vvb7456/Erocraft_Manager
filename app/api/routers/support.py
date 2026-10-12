"""Account-scoped support chat; durable cursors also work across web workers."""

from __future__ import annotations

import asyncio
import io
import json
import warnings
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.deps.auth import get_current_user, require_admin
from app.api.deps.db import get_db
from app.core.time import to_iso_z, utc_naive_now
from app.db.models.pterodactyl import PteroUser
from app.db.models.support import SupportConversation, SupportMessage
from app.db.session import get_session_factory

router = APIRouter(prefix="/support", tags=["support"])
_MAX_IMAGE = 4 * 1024 * 1024


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
        "created_at": to_iso_z(message.created_at),
        "image_url": f"/api/support/messages/{message.id}/image" if message.image_type else None,
    }


async def conversation(db: AsyncSession, cid: int, user: PteroUser, *, lock: bool = False) -> SupportConversation:
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
async def my_conversation(user: PteroUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    uid = user.id
    row = await db.scalar(select(SupportConversation).where(SupportConversation.user_id == uid))
    if row is None:
        try:
            row = SupportConversation(user_id=uid)
            db.add(row)
            await db.commit()
        except IntegrityError:
            await db.rollback()
            row = await db.scalar(select(SupportConversation).where(SupportConversation.user_id == uid))
    assert row is not None
    return {"id": row.id, "user_read_id": row.user_read_id, "admin_read_id": row.admin_read_id}


@router.get("/unread")
async def unread_count(user: PteroUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    stmt = select(func.count(SupportMessage.id)).join(SupportConversation, SupportConversation.id == SupportMessage.conversation_id)
    if user.root_admin:
        stmt = stmt.where(SupportMessage.is_admin.is_(False), SupportMessage.id > SupportConversation.admin_read_id)
    else:
        stmt = stmt.where(SupportConversation.user_id == user.id, SupportMessage.is_admin.is_(True), SupportMessage.id > SupportConversation.user_read_id)
    return {"unread": await db.scalar(stmt) or 0}


@router.get("/conversations")
async def list_conversations(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    unread = select(func.count(SupportMessage.id)).where(
        SupportMessage.conversation_id == SupportConversation.id,
        SupportMessage.id > SupportConversation.admin_read_id,
        SupportMessage.is_admin.is_(False),
    ).correlate(SupportConversation).scalar_subquery()
    rows = (await db.execute(
        select(SupportConversation, PteroUser.username, unread, SupportMessage.content, SupportMessage.image_type)
        .join(PteroUser, PteroUser.id == SupportConversation.user_id)
        .outerjoin(SupportMessage, SupportMessage.id == SupportConversation.last_message_id)
        .where(SupportConversation.last_message_id > 0)
        .order_by(SupportConversation.updated_at.desc(), SupportConversation.id.desc())
        .offset(offset).limit(limit + 1)
    )).all()
    return {"has_more": len(rows) > limit, "items": [
        {"id": c.id, "username": name, "user_id": c.user_id, "unread": count,
         "preview": (text or "")[:100], "has_image": bool(image), "updated_at": to_iso_z(c.updated_at)}
        for c, name, count, text, image in rows[:limit]
    ]}


@router.get("/conversations/{cid}/messages")
async def messages(
    cid: int, after: int = Query(0, ge=0), before: int = Query(0, ge=0),
    user: PteroUser = Depends(get_current_user), db: AsyncSession = Depends(get_db),
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


def normalize_image(data: bytes) -> tuple[bytes, str]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > 16_000_000:
                    raise ValueError()
                image.load()
                image.thumbnail((2400, 2400))
                output = io.BytesIO()
                image.convert("RGB").save(output, format="JPEG", quality=88)
                return output.getvalue(), "image/jpeg"
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(400, "请上传有效的 PNG、JPEG 或 WebP 截图（不超过1600万像素）") from exc


@router.post("/conversations/{cid}/messages")
async def send_message(cid: int, request: Request, user: PteroUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
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
                    image_data, image_type = await run_in_threadpool(normalize_image, data)
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
    message = SupportMessage(
        conversation_id=cid, sender_id=user.id, is_admin=bool(user.root_admin),
        client_id=payload.client_id, content=content, image_data=image_data, image_type=image_type,
    )
    db.add(message)
    await db.flush()
    row.last_message_id = message.id
    row.updated_at = message.created_at
    await db.commit()
    return message_out(message)


@router.post("/conversations/{cid}/read")
async def mark_read(cid: int, payload: ReadInput, user: PteroUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    row = await conversation(db, cid, user)
    cursor = min(payload.message_id, row.last_message_id)
    column = SupportConversation.admin_read_id if user.root_admin else SupportConversation.user_read_id
    await db.execute(update(SupportConversation).where(SupportConversation.id == cid, column < cursor).values({column.key: cursor}))
    await db.commit()
    return {"ok": True}


@router.get("/messages/{mid}/image")
async def image(mid: int, user: PteroUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> Response:
    message = await db.get(SupportMessage, mid)
    if message is None or not message.image_type:
        raise HTTPException(404, "截图不存在")
    await conversation(db, message.conversation_id, user)
    data = await db.scalar(select(SupportMessage.image_data).where(SupportMessage.id == mid))
    return Response(data, media_type=message.image_type, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/events")
async def events(request: Request, user: PteroUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    uid, admin = user.id, bool(user.root_admin)
    await db.commit()

    async def stream():
        previous = None
        yield "retry: 2000\n\n"
        for _ in range(30):
            if await request.is_disconnected():
                return
            async with get_session_factory()() as db:
                current = await db.get(PteroUser, uid)
                if current is None or bool(current.root_admin) != admin:
                    yield "event: expired\ndata: {}\n\n"
                    return
                stmt = select(func.sum(SupportConversation.last_message_id), func.sum(SupportConversation.user_read_id), func.sum(SupportConversation.admin_read_id))
                if not admin:
                    stmt = stmt.where(SupportConversation.user_id == uid)
                signature = tuple(str(x or 0) for x in (await db.execute(stmt)).one())
            if signature != previous:
                yield f"event: change\ndata: {json.dumps(signature)}\n\n"
                previous = signature
            else:
                yield ": heartbeat\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
