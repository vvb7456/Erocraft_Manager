"""A native mini-program console with its own limited, revocable authentication."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import secrets

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.db import get_db
from app.api.deps.miniprogram import get_mini_session, get_mini_user, session_required, token_hash
from app.api.deps.support import SupportUser
from app.api.routers import support, user_servers
from app.api.utils.wings_errors import translate_wings_error
from app.core.api_errors import ApiError
from app.core.contracts import ErrorInfo, OperationResult
from app.core.rate_limit import limiter
from app.core.operation import set_operation
from app.core.settings_store import get_settings_store
from app.core.time import to_iso_z, utc_naive_now
from app.db.models.billing import BillingOrder
from app.db.models.miniprogram import MiniProgramBinding, MiniProgramSession
from app.db.models.pterodactyl import PteroServer, PteroUser
from app.db.repositories.servers import exclude_placeholders, server_repository
from app.db.repositories.users import user_repository
from app.schemas.miniprogram import (
    MiniBindInput, MiniLoginInput, MiniLoginOut, MiniOrder, MiniOrders,
    MiniServer, MiniServerStatus, MiniUser,
)
from app.schemas.user_servers import PowerActionRequest
from app.services import wechat_client
from app.services.audit import log_manager_activity
from app.services.billing.gateway.base import GatewayBusinessError, GatewayTransientError
from app.services.wings import WingsServiceError, wings_service


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/miniprogram", tags=["miniprogram"], dependencies=[Depends(no_store)])


async def record(db: AsyncSession, action: str, key: str, user: PteroUser | None, error: ErrorInfo | None = None) -> OperationResult:
    operation = OperationResult(
        action=action, phase="request" if error else "execution", outcome="failed" if error else "success",
        target={"user_id": user.id} if user else {}, error=error,
    )
    await log_manager_activity(db, actor=user.username if user else "system", category="auth",
                               operation=operation, detail_key=key,
                               detail_params={"username": user.username if user else "—"})
    return set_operation(operation)


def new_session(db: AsyncSession, appid: str, openid: str, binding_id: int | None) -> tuple[str, MiniProgramSession]:
    token = secrets.token_urlsafe(32)
    session = MiniProgramSession(token_hash=token_hash(token), appid=appid, openid=openid,
                                 binding_id=binding_id,
                                 expires_at=utc_naive_now() + (timedelta(days=7) if binding_id else timedelta(minutes=5)))
    db.add(session)
    return token, session


@router.post("/login", response_model=MiniLoginOut)
@limiter.limit("20/minute")
async def login(payload: MiniLoginInput, request: Request, db: AsyncSession = Depends(get_db)) -> MiniLoginOut:
    values = await get_settings_store().get_many(db, {"WECHAT_PAY_MINIPROGRAM_APPID": "", "WECHAT_PAY_MINIPROGRAM_APP_SECRET": ""})
    appid, secret = str(values["WECHAT_PAY_MINIPROGRAM_APPID"]), str(values["WECHAT_PAY_MINIPROGRAM_APP_SECRET"])
    if not appid or not secret:
        raise ApiError(503, "miniprogram.login_unavailable")
    try:
        openid = await wechat_client.openid(appid, secret, payload.code, mini=True)
    except GatewayTransientError as exc:
        raise ApiError(502, "dependency.unreachable") from exc
    except GatewayBusinessError as exc:
        raise ApiError(422, "miniprogram.login_failed") from exc
    binding = await db.scalar(select(MiniProgramBinding).where(MiniProgramBinding.appid == appid, MiniProgramBinding.openid == openid))
    user = await db.get(PteroUser, binding.user_id) if binding else None
    if binding and user is None:
        await db.delete(binding)
        await db.flush()
        binding = None
    token, session = new_session(db, appid, openid, binding.id if binding else None)
    await db.commit()
    operation = await record(db, "auth.wechat.login", "wechat_login" if user else "wechat_verified", user)
    return MiniLoginOut(token=token, expires_at=to_iso_z(session.expires_at),
                        user=MiniUser(id=user.id, username=user.username) if user else None, operation=operation)


@router.post("/bind", response_model=MiniLoginOut)
@limiter.limit("10/minute")
async def bind(payload: MiniBindInput, request: Request, session: MiniProgramSession = Depends(get_mini_session),
               db: AsyncSession = Depends(get_db)) -> MiniLoginOut:
    if session.binding_id is not None:
        raise ApiError(409, "miniprogram.binding_conflict")
    user = await user_repository.get_by_username_or_email(db, payload.username.strip())
    valid = user is not None and len(payload.password.encode()) <= 72 and await asyncio.to_thread(user.check_password, payload.password)
    if not valid:
        operation = await record(db, "auth.wechat.bind", "wechat_binding", user, ErrorInfo(code="auth.invalid_credentials"))
        raise ApiError(422, "auth.invalid_credentials", operation=operation)
    assert user is not None
    locked = await db.scalar(select(MiniProgramSession).where(MiniProgramSession.token_hash == session.token_hash).with_for_update())
    if locked is None or locked.expires_at <= utc_naive_now():
        raise session_required()
    binding = MiniProgramBinding(appid=locked.appid, openid=locked.openid, user_id=user.id, created_at=utc_naive_now())
    db.add(binding)
    try:
        await db.flush()
        token, authenticated = new_session(db, locked.appid, locked.openid, binding.id)
        await db.delete(locked)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        # Rollback expires ORM values; reload before writing the audit entry.
        user = await user_repository.get_by_username_or_email(db, payload.username.strip())
        operation = await record(db, "auth.wechat.bind", "wechat_binding", user, ErrorInfo(code="miniprogram.binding_conflict"))
        raise ApiError(409, "miniprogram.binding_conflict", operation=operation) from exc
    operation = await record(db, "auth.wechat.bind", "wechat_binding", user)
    return MiniLoginOut(token=token, expires_at=to_iso_z(authenticated.expires_at),
                        user=MiniUser(id=user.id, username=user.username), operation=operation)


@router.get("/me", response_model=MiniUser)
async def me(user: PteroUser = Depends(get_mini_user)) -> MiniUser:
    return MiniUser(id=user.id, username=user.username)


@router.post("/logout", status_code=204)
async def logout(session: MiniProgramSession = Depends(get_mini_session), db: AsyncSession = Depends(get_db)) -> None:
    binding = await db.get(MiniProgramBinding, session.binding_id) if session.binding_id else None
    user = await db.get(PteroUser, binding.user_id) if binding else None
    await db.delete(session)
    await db.commit()
    await record(db, "auth.wechat.logout", "wechat_logout", user)


@router.delete("/binding", status_code=204)
async def unbind(user: PteroUser = Depends(get_mini_user), session: MiniProgramSession = Depends(get_mini_session),
                 db: AsyncSession = Depends(get_db)) -> None:
    binding_id, appid, openid = session.binding_id, session.appid, session.openid
    await db.execute(delete(MiniProgramSession).where(MiniProgramSession.appid == appid, MiniProgramSession.openid == openid))
    await db.execute(delete(MiniProgramBinding).where(MiniProgramBinding.id == binding_id))
    await db.commit()
    await record(db, "auth.wechat.unbind", "wechat_unbinding", user)


@router.get("/servers", response_model=list[MiniServer])
async def servers(user: PteroUser = Depends(get_mini_user), db: AsyncSession = Depends(get_db)) -> list[MiniServer]:
    items = await server_repository.list_for_owner(db, user.id)
    return [MiniServer(id=s.id, name=s.name, status=s.status, suspended=s.is_suspended,
                       installing=s.status == "installing" or s.installed_at is None,
                       expires_on=s.expiration_date.isoformat() if s.expiration_date else None,
                       node=s.node.name if s.node else "") for s in items]


async def owned_server(server_id: int, user: PteroUser = Depends(get_mini_user), db: AsyncSession = Depends(get_db)) -> PteroServer:
    server = await db.scalar(select(PteroServer).where(PteroServer.id == server_id, PteroServer.owner_id == user.id, exclude_placeholders()))
    if server is None:
        raise ApiError(404, "resource.not_found")
    return server


@router.get("/servers/{server_id}/status", response_model=MiniServerStatus)
async def server_status(server: PteroServer = Depends(owned_server), db: AsyncSession = Depends(get_db)) -> MiniServerStatus:
    try:
        data = await wings_service.get_server(db, server.node_id, server.uuid)
    except WingsServiceError as exc:
        raise translate_wings_error(exc) from exc
    if data.get("state") not in ("running", "offline", "starting", "stopping"):
        raise ApiError(502, "dependency.invalid_response")
    return MiniServerStatus(state=data["state"], suspended=bool(data.get("is_suspended", server.is_suspended)))


@router.post("/servers/{server_id}/power", status_code=204)
async def server_power(payload: PowerActionRequest, request: Request,
                       server: PteroServer = Depends(owned_server), user: PteroUser = Depends(get_mini_user),
                       db: AsyncSession = Depends(get_db)) -> Response:
    if not server.is_suspended and (server.status == "installing" or server.installed_at is None):
        raise ApiError(409, "server.installing")
    response = await user_servers.send_user_server_power_action(
        payload=payload, request=request, current_user=user, server=server, db=db,
    )
    set_operation(OperationResult(action=f"server.power.{payload.action}", phase="acceptance", outcome="success",
                                  target={"server_id": server.id}))
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/orders", response_model=MiniOrders)
async def orders(offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50),
                 user: PteroUser = Depends(get_mini_user), db: AsyncSession = Depends(get_db)) -> MiniOrders:
    rows = list((await db.scalars(select(BillingOrder).where(BillingOrder.user_id == user.id)
                                 .order_by(BillingOrder.created_at.desc(), BillingOrder.id.desc()).offset(offset).limit(limit + 1))).all())
    return MiniOrders(items=[MiniOrder(
        id=o.id, order_no=o.order_no, title=str((o.plan_snapshot or {}).get("plan_name") or "服务订单"),
        kind=o.kind, status=o.status, total_fen=o.total_fen, received_fen=o.received_fen, refunded_fen=o.refunded_fen,
        total_days=o.total_days, currency=str((o.plan_snapshot or {}).get("currency_code", "CNY")),
        created_at=to_iso_z(o.created_at), applied_at=to_iso_z(o.applied_at) if o.applied_at else None,
    ) for o in rows[:limit]], has_more=len(rows) > limit)


async def chat_user(user: PteroUser = Depends(get_mini_user)) -> SupportUser:
    # Even an administrator's mini-program is restricted to their own customer conversation.
    return SupportUser(user.id, user.username)


@router.post("/support/conversation")
async def conversation(user: SupportUser = Depends(chat_user), db: AsyncSession = Depends(get_db)) -> dict:
    return await support.my_conversation(user=user, db=db)


def mini_message(message: dict) -> dict:
    if message.get("image_url"):
        message["image_url"] = f"/api/miniprogram/support/messages/{message['id']}/image"
    return message


@router.get("/support/conversations/{cid}/messages")
async def messages(cid: int, after: int = Query(0, ge=0), before: int = Query(0, ge=0),
                   user: SupportUser = Depends(chat_user), db: AsyncSession = Depends(get_db)) -> dict:
    result = await support.messages(cid=cid, after=after, before=before, user=user, db=db)
    result["items"] = [mini_message(message) for message in result["items"]]
    return result


@router.post("/support/conversations/{cid}/messages")
async def send_message(cid: int, request: Request, user: SupportUser = Depends(chat_user), db: AsyncSession = Depends(get_db)) -> dict:
    return mini_message(await support.send_message(cid=cid, request=request, user=user, db=db))


@router.post("/support/conversations/{cid}/read")
async def read_messages(cid: int, payload: support.ReadInput, user: SupportUser = Depends(chat_user), db: AsyncSession = Depends(get_db)) -> dict:
    return await support.mark_read(cid=cid, payload=payload, user=user, db=db)


@router.get("/support/messages/{mid}/image")
async def image(mid: int, user: SupportUser = Depends(chat_user), db: AsyncSession = Depends(get_db)) -> Response:
    return await support.image(mid=mid, user=user, db=db)
