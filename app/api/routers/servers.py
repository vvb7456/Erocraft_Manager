"""Admin server management routes."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import selectinload

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.runtime_settings import AUTOMATION_SPECS, SETTINGS_SPECS
from app.core.settings_store import get_settings_store
from app.core.time import local_today
from app.db.models import Egg, PteroServer, PteroUser, ServerMeta
from app.db.models.billing import BillingPlan
from app.db.repositories.servers import exclude_placeholders, server_repository
from app.schemas.servers import (
    BatchServersRequest,
    BatchServersResponse,
    CreateServerRequest,
    CreateServerResponse,
    MessageResponse,
    RenewServerRequest,
    ServersListResponse,
    ServerListItem,
    ToggleSuspendResponse,
    UpdateServerPlanRequest,
    UpdateServerRequest,
)
from app.services.audit import log_manager_activity
from app.services.email import get_email_delay, get_site_url, load_template, render_template_body, send_email
from app.services import server_lifecycle
from app.services.server_lifecycle import LifecycleError, LifecycleValidationError

router = APIRouter(prefix="/admin", tags=["servers"])
logger = logging.getLogger(__name__)


def _classify_server(expiration_date: date | None, today: date) -> tuple[int | None, str]:
    days_left = None
    status_label = "permanent"
    if expiration_date is not None:
        days_left = (expiration_date - today).days
        if days_left < 0:
            status_label = "expired"
        elif days_left <= 7:
            status_label = "expiring_soon"
        else:
            status_label = "normal"
    return days_left, status_label


async def _get_server_or_404(db: AsyncSession, server_id: int) -> PteroServer:
    server = await server_repository.get_by_id(db, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="服务器不存在")
    return server


async def _get_today(db: AsyncSession) -> date:
    timezone_name = await get_settings_store().get(
        db,
        "TIMEZONE",
        AUTOMATION_SPECS["TIMEZONE"].default_value(),
    )
    return local_today(str(timezone_name))


async def _server_defaults(db: AsyncSession) -> dict[str, int | str]:
    store = get_settings_store()
    defaults = {
        "DOCKER_IMAGE": SETTINGS_SPECS["DOCKER_IMAGE"].default_value(),
        "DEFAULT_CPU": SETTINGS_SPECS["DEFAULT_CPU"].default_value(),
        "DEFAULT_MEMORY": SETTINGS_SPECS["DEFAULT_MEMORY"].default_value(),
        "DEFAULT_DISK": SETTINGS_SPECS["DEFAULT_DISK"].default_value(),
        "DEFAULT_DATABASES": SETTINGS_SPECS["DEFAULT_DATABASES"].default_value(),
        "DEFAULT_BACKUPS": SETTINGS_SPECS["DEFAULT_BACKUPS"].default_value(),
        "DEFAULT_ALLOCATIONS": SETTINGS_SPECS["DEFAULT_ALLOCATIONS"].default_value(),
    }
    return await store.get_many(db, defaults)


async def _apply_plan_change(
    db: AsyncSession,
    server: PteroServer,
    new_plan_id: int | None,
) -> tuple[BillingPlan | None, BillingPlan | None]:
    """Update manager_server_meta.plan_id for a server (no resource side effects).

    Returns (old_plan, new_plan) where each may be None. Raises HTTPException if new_plan_id is invalid.
    """
    old_plan: BillingPlan | None = None
    new_plan: BillingPlan | None = None

    meta = server.meta
    old_plan_id = meta.plan_id if meta is not None else None
    if old_plan_id is not None:
        old_plan = await db.get(BillingPlan, old_plan_id)

    if new_plan_id is not None:
        new_plan = await db.get(BillingPlan, new_plan_id)
        if new_plan is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="套餐不存在")

    if meta is None:
        db.add(ServerMeta(server_id=server.id, plan_id=new_plan_id))
    else:
        meta.plan_id = new_plan_id

    return old_plan, new_plan


async def _set_meta_expiration(db: AsyncSession, server_id: int, expiration_date: date) -> None:
    values = {"server_id": server_id, "expiration_date": expiration_date}
    dialect_name = (await db.connection()).dialect.name

    if dialect_name == "mysql":
        stmt = mysql_insert(ServerMeta).values(**values)
        await db.execute(
            stmt.on_duplicate_key_update(
                expiration_date=stmt.inserted.expiration_date,
            )
        )
        return

    if dialect_name == "sqlite":
        stmt = sqlite_insert(ServerMeta).values(**values)
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=[ServerMeta.server_id],
                set_={"expiration_date": expiration_date},
            )
        )
        return

    meta = await db.get(ServerMeta, server_id)
    if meta is None:
        db.add(ServerMeta(**values))
    else:
        meta.expiration_date = expiration_date


async def _persist_expiration_after_remote(
    db: AsyncSession,
    *,
    server_id: int,
    new_date: date,
    old_date: date | None,
    resuspend_on_failure: bool = False,
) -> None:
    original_exc: Exception | None = None
    try:
        await _set_meta_expiration(db, server_id, new_date)
        await db.commit()
        return
    except Exception as exc:
        original_exc = exc
        await db.rollback()

    cleanup_attempted = False
    cleanup_failed: list[str] = []

    if old_date is not None:
        cleanup_attempted = True
        try:
            await server_lifecycle.update_server_expiration_description(db, server_id, old_date)
            await db.commit()
        except LifecycleError:
            await db.rollback()
            cleanup_failed.append("恢复面板到期描述失败")
            logger.exception("Failed to restore server %s description after local persistence failure", server_id)

    if resuspend_on_failure:
        cleanup_attempted = True
        try:
            await server_lifecycle.suspend_server(db, server_id)
        except LifecycleError:
            await db.rollback()
            cleanup_failed.append("恢复面板冻结状态失败")
            logger.exception("Failed to restore server %s suspension after local persistence failure", server_id)

    logger.exception(
        "Failed to persist expiration metadata for server %s",
        server_id,
        exc_info=original_exc,
    )
    detail = "面板更新成功，但写入管理元数据失败"
    if cleanup_attempted and not cleanup_failed:
        detail += "，已自动回滚远端变更"
    elif cleanup_failed:
        detail += "，且" + "；".join(cleanup_failed) + "，请检查面板状态"
    else:
        detail += "，请检查面板状态"
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail) from original_exc


@router.get("/servers", response_model=ServersListResponse)
async def list_servers(
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ServersListResponse:
    today = await _get_today(db)
    servers = await server_repository.list_for_admin(db)

    egg_ids = sorted({server.egg_id for server in servers if server.egg_id})
    egg_names: dict[int, str] = {}
    if egg_ids:
        rows = await db.execute(select(Egg.id, Egg.name).where(Egg.id.in_(egg_ids)))
        egg_names = {egg_id: egg_name for egg_id, egg_name in rows.all()}

    plan_ids = sorted({
        server.meta.plan_id
        for server in servers
        if server.meta is not None and server.meta.plan_id is not None
    })
    plans: dict[int, BillingPlan] = {}
    if plan_ids:
        rows = await db.execute(
            select(BillingPlan).where(BillingPlan.id.in_(plan_ids))
        )
        plans = {p.id: p for p in rows.scalars().all()}

    items: list[ServerListItem] = []
    for server in servers:
        expiration_date = server.expiration_date
        days_left, status_label = _classify_server(expiration_date, today)
        meta_plan_id = server.meta.plan_id if server.meta is not None else None
        plan_obj = plans.get(meta_plan_id) if meta_plan_id is not None else None
        items.append(
            ServerListItem(
                pteroId=server.id,
                uuid=server.uuid,
                name=server.name,
                ownerId=server.owner_id,
                ownerUsername=server.owner.username if server.owner else None,
                eggName=egg_names.get(server.egg_id),
                expirationDate=expiration_date.isoformat() if expiration_date else None,
                daysLeft=days_left,
                statusLabel=status_label,
                isSuspended=server.is_suspended,
                planId=meta_plan_id,
                planCode=plan_obj.code if plan_obj else None,
                planName=plan_obj.display_name if plan_obj else None,
            )
        )

    return ServersListResponse(servers=items)


@router.post("/servers", response_model=CreateServerResponse, status_code=status.HTTP_201_CREATED)
async def create_server(
    payload: CreateServerRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CreateServerResponse:
    actor_username = current_user.username
    defaults = await _server_defaults(db)
    today = await _get_today(db)
    expiration_date = today + timedelta(days=payload.expiration_days)

    # Resolve nest_id from egg (panel API used to derive it server-side)
    egg_row = await db.execute(select(Egg.nest_id).where(Egg.id == payload.egg_id))
    nest_id = egg_row.scalar_one_or_none()
    if nest_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Egg {payload.egg_id} 不存在")

    description = f"到期时间：{expiration_date.strftime('%Y/%m/%d')}"
    await db.commit()

    try:
        created = await server_lifecycle.create_server(
            db,
            owner_id=payload.user_id,
            node_id=payload.node_id,
            allocation_id=payload.allocation_id,
            egg_id=payload.egg_id,
            nest_id=int(nest_id),
            name=payload.server_name.strip(),
            description=description,
            image=(payload.docker_image or str(defaults["DOCKER_IMAGE"])).strip(),
            startup=payload.startup_command.strip(),
            environment=payload.environment,
            cpu=int(payload.cpu if payload.cpu is not None else defaults["DEFAULT_CPU"]),
            memory=int(payload.memory if payload.memory is not None else defaults["DEFAULT_MEMORY"]),
            disk=int(payload.disk if payload.disk is not None else defaults["DEFAULT_DISK"]),
            database_limit=int(payload.databases if payload.databases is not None else defaults["DEFAULT_DATABASES"]),
            backup_limit=int(payload.backups if payload.backups is not None else defaults["DEFAULT_BACKUPS"]),
            allocation_limit=int(payload.allocations if payload.allocations is not None else defaults["DEFAULT_ALLOCATIONS"]),
        )
    except LifecycleValidationError as exc:
        # User-correctable input error → 422 so the frontend can show a field-level message.
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except LifecycleError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    server_id = int(created.id)

    try:
        await _set_meta_expiration(db, server_id, expiration_date)
        # Bind plan if requested (after meta row exists).
        if payload.plan_id is not None:
            plan_obj = await db.get(BillingPlan, payload.plan_id)
            if plan_obj is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"套餐 {payload.plan_id} 不存在",
                )
            meta = await db.get(ServerMeta, server_id)
            if meta is not None:
                meta.plan_id = payload.plan_id
        await db.commit()
    except Exception as exc:
        await db.rollback()
        cleanup_succeeded = False
        try:
            await server_lifecycle.delete_server(db, server_id)
            cleanup_succeeded = True
        except LifecycleError:
            await db.rollback()
            logger.exception("Failed to clean up server %s after local persistence failure", server_id)

        logger.exception("Failed to persist manager metadata for server %s", server_id)
        detail = "服务器已创建，但写入管理元数据失败"
        if cleanup_succeeded:
            detail += "，已自动回滚"
        else:
            detail += "，且自动回滚失败，请检查面板状态"
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail) from exc

    server_data = {
        "id": created.id,
        "uuid": created.uuid,
        "uuid_short": created.uuid_short,
        "name": created.name,
        "owner_id": created.owner_id,
        "node_id": created.node_id,
        "allocation_id": created.allocation_id,
    }

    await log_manager_activity(
        db,
        actor=actor_username,
        category="server",
        status="success",
        detail_key="create_server",
        detail_params={"actor": actor_username, "server_name": payload.server_name, "server_id": server_id},
    )
    return CreateServerResponse(
        message=f"服务器 '{payload.server_name}' 创建成功",
        server=server_data,
    )


@router.post("/servers/{server_id}/renew", response_model=MessageResponse)
async def renew_server(
    server_id: int,
    payload: RenewServerRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    server = await _get_server_or_404(db, server_id)
    actor_username = current_user.username
    server_name = server.name
    was_suspended = server.is_suspended
    old_expiration_date = server.expiration_date
    try:
        new_date = date.fromisoformat(payload.date)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="日期格式无效，请使用 YYYY-MM-DD") from exc

    await db.commit()
    try:
        await server_lifecycle.update_server_expiration_description(db, server_id, new_date)
        await db.commit()
        if was_suspended:
            await server_lifecycle.unsuspend_server(db, server_id)
    except LifecycleError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await _persist_expiration_after_remote(
        db,
        server_id=server_id,
        new_date=new_date,
        old_date=old_expiration_date,
        resuspend_on_failure=was_suspended,
    )
    await log_manager_activity(
        db,
        actor=actor_username,
        category="server",
        status="success",
        detail_key="renew_server",
        detail_params={"actor": actor_username, "server_name": server_name, "server_id": server_id, "date": new_date.isoformat()},
    )
    return MessageResponse(message=f"已续期至 {new_date.isoformat()}")


@router.post("/servers/{server_id}/suspend", response_model=ToggleSuspendResponse)
async def toggle_suspend(
    server_id: int,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ToggleSuspendResponse:
    server = await _get_server_or_404(db, server_id)
    was_suspended = server.is_suspended
    action_text = "解冻" if was_suspended else "冻结"

    try:
        if was_suspended:
            await server_lifecycle.unsuspend_server(db, server_id)
        else:
            await server_lifecycle.suspend_server(db, server_id)
    except LifecycleError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        status="success",
        detail_key="unsuspend_server" if was_suspended else "suspend_server",
        detail_params={"actor": current_user.username, "server_name": server.name, "server_id": server_id},
    )
    return ToggleSuspendResponse(message=f"服务器已{action_text}", isSuspended=not was_suspended)


@router.post("/servers/batch", response_model=BatchServersResponse)
async def batch_servers(
    payload: BatchServersRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BatchServersResponse:
    success = 0
    errors = 0
    action = payload.action
    server_ids = payload.serverIds
    actor_username = current_user.username

    if action in {"suspend", "unsuspend"}:
        for server_id in server_ids:
            try:
                if action == "suspend":
                    await server_lifecycle.suspend_server(db, server_id)
                else:
                    await server_lifecycle.unsuspend_server(db, server_id)
                success += 1
            except LifecycleError:
                await db.rollback()
                errors += 1

        await log_manager_activity(
            db,
            actor=actor_username,
            category="server",
            status="failure" if errors else "success",
            detail_key=f"batch_{action}",
            detail_params={"success": success, "failed": errors},
        )
        return BatchServersResponse(
            message=f"操作完成：成功 {success}，失败 {errors}",
            success=success,
            failed=errors,
        )

    if action == "renew":
        if payload.days is None or payload.days <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="续期天数无效")

        today = await _get_today(db)
        rows = await db.execute(
            select(PteroServer)
            .options(selectinload(PteroServer.meta))
            .where(PteroServer.id.in_(server_ids), exclude_placeholders())
            .order_by(PteroServer.id.asc())
        )
        servers = list(rows.scalars().all())
        await db.commit()

        for server in servers:
            was_suspended = server.is_suspended
            old_expiration_date = server.expiration_date
            base_date = today if old_expiration_date and old_expiration_date < today else (old_expiration_date or today)
            new_date = base_date + timedelta(days=payload.days)
            try:
                await server_lifecycle.update_server_expiration_description(db, server.id, new_date)
                await db.commit()
                if was_suspended:
                    await server_lifecycle.unsuspend_server(db, server.id)
                await _persist_expiration_after_remote(
                    db,
                    server_id=server.id,
                    new_date=new_date,
                    old_date=old_expiration_date,
                    resuspend_on_failure=was_suspended,
                )
                success += 1
            except (LifecycleError, HTTPException):
                await db.rollback()
                errors += 1

        await log_manager_activity(
            db,
            actor=actor_username,
            category="server",
            status="failure" if errors else "success",
            detail_key="batch_renew",
            detail_params={"success": success, "failed": errors},
        )
        return BatchServersResponse(
            message=f"操作完成：成功 {success}，失败 {errors}",
            success=success,
            failed=errors,
        )

    if action == "delete":
        for server_id in server_ids:
            try:
                await server_lifecycle.delete_server(db, server_id)
                success += 1
            except LifecycleError:
                # Discard any half-applied state from the failed lifecycle call
                # so the next iteration / audit log starts on a clean session.
                await db.rollback()
                errors += 1

        await log_manager_activity(
            db,
            actor=actor_username,
            category="server",
            status="failure" if errors else "success",
            detail_key="batch_delete",
            detail_params={"success": success, "failed": errors},
        )
        return BatchServersResponse(
            message=f"操作完成：成功 {success}，失败 {errors}",
            success=success,
            failed=errors,
        )

    if action == "update_plan":
        new_plan_id = payload.planId
        if new_plan_id is not None:
            target = await db.get(BillingPlan, new_plan_id)
            if target is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="套餐不存在")

        rows = await db.execute(
            select(PteroServer)
            .options(selectinload(PteroServer.meta))
            .where(PteroServer.id.in_(server_ids), exclude_placeholders())
            .order_by(PteroServer.id.asc())
        )
        servers = list(rows.scalars().all())

        for server in servers:
            try:
                old_plan, new_plan = await _apply_plan_change(db, server, new_plan_id)
                await db.commit()
                await log_manager_activity(
                    db,
                    actor=actor_username,
                    category="server",
                    status="success",
                    detail_key="admin_server.plan.update",
                    detail_params={
                        "server_name": server.name,
                        "server_id": server.id,
                        "old_plan": old_plan.display_name if old_plan else "—",
                        "new_plan": new_plan.display_name if new_plan else "—",
                    },
                )
                success += 1
            except HTTPException:
                await db.rollback()
                errors += 1
            except Exception:
                await db.rollback()
                errors += 1
                logger.exception("Failed to update plan for server %s", server.id)

        return BatchServersResponse(
            message=f"操作完成：成功 {success}，失败 {errors}",
            success=success,
            failed=errors,
        )

    template = await load_template(db, "bulk")
    brand_name = await get_settings_store().get(
        db,
        "BRAND_NAME",
        SETTINGS_SPECS["BRAND_NAME"].default_value(),
    )
    site_url = await get_site_url(db)
    delay = await get_email_delay(db)
    rows = await db.execute(
        select(PteroServer)
        .options(selectinload(PteroServer.meta), selectinload(PteroServer.owner))
        .where(PteroServer.id.in_(server_ids), exclude_placeholders())
        .order_by(PteroServer.id.asc())
    )
    servers = list(rows.scalars().all())
    await db.commit()

    for index, server in enumerate(servers):
        owner = server.owner
        if owner is None or not owner.email:
            errors += 1
            continue

        expiration_date = server.expiration_date.isoformat() if server.expiration_date else "永久"
        subject, body = render_template_body(
            template,
            {
                "brand_name": str(brand_name),
                "username": owner.username,
                "email": owner.email,
                "server_name": server.name,
                "server_id": server.id,
                "expiration_date": expiration_date,
            },
        )
        sent, _ = await send_email(
            db,
            recipient_email=owner.email,
            subject=subject,
            main_content_raw=body,
            greeting=f"您好, {owner.username}!",
            action_text="登录系统查看",
            action_url=site_url,
        )
        if sent:
            success += 1
        else:
            errors += 1
        if delay > 0 and index < len(servers) - 1:
            await asyncio.sleep(delay)

    await log_manager_activity(
        db,
        actor=actor_username,
        category="server",
        status="failure" if errors else "success",
        detail_key="batch_email",
        detail_params={"success": success, "failed": errors},
    )
    return BatchServersResponse(
        message=f"操作完成：成功 {success}，失败 {errors}",
        success=success,
        failed=errors,
    )


@router.delete("/servers/{server_id}", response_model=MessageResponse)
async def delete_server(
    server_id: int,
    force: bool = Query(default=False),
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    server = await _get_server_or_404(db, server_id)
    try:
        await server_lifecycle.delete_server(db, server_id, force=force)
    except LifecycleError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        status="success",
        detail_key="delete_server",
        detail_params={"actor": current_user.username, "server_name": server.name, "server_id": server_id},
    )
    if force:
        return MessageResponse(message=f"服务器 '{server.name}' 已强制删除")
    return MessageResponse(message=f"服务器 '{server.name}' 已删除")


@router.put("/servers/{server_id}", response_model=MessageResponse)
async def update_server(
    server_id: int,
    payload: UpdateServerRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    server = await _get_server_or_404(db, server_id)
    actor_username = current_user.username
    server_name = server.name
    old_expiration_date = server.expiration_date
    if not payload.expirationDate:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无有效更新内容")

    try:
        new_date = date.fromisoformat(payload.expirationDate)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="日期格式无效") from exc

    await db.commit()
    try:
        await server_lifecycle.update_server_expiration_description(db, server_id, new_date)
        await db.commit()
    except LifecycleError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await _persist_expiration_after_remote(
        db,
        server_id=server_id,
        new_date=new_date,
        old_date=old_expiration_date,
    )
    await log_manager_activity(
        db,
        actor=actor_username,
        category="server",
        status="success",
        detail_key="set_expiry",
        detail_params={"actor": actor_username, "server_name": server_name, "server_id": server_id, "date": new_date.isoformat()},
    )
    return MessageResponse(message=f"到期日期已更新为 {new_date.isoformat()}")


@router.patch("/servers/{server_id}/plan", response_model=MessageResponse)
async def update_server_plan(
    server_id: int,
    payload: UpdateServerPlanRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Update only the plan binding of a server. Does not touch resources, image, startup, or expiration."""
    server = await server_repository.get_by_id(db, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="服务器不存在")
    # Ensure meta is loaded
    await db.refresh(server, attribute_names=["meta"])

    try:
        old_plan, new_plan = await _apply_plan_change(db, server, payload.planId)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.exception("Failed to update plan for server %s", server_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新套餐绑定失败") from exc

    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        status="success",
        detail_key="admin_server.plan.update",
        detail_params={
            "server_name": server.name,
            "server_id": server_id,
            "old_plan": old_plan.display_name if old_plan else "—",
            "new_plan": new_plan.display_name if new_plan else "—",
        },
    )
    return MessageResponse(message="套餐绑定已更新")
