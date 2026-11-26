"""Admin server management routes."""

from __future__ import annotations
from app.core.operation import batch_operation

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.runtime_settings import AUTOMATION_SPECS, SETTINGS_SPECS
from app.core.settings_store import get_settings_store
from app.core.time import local_today, utc_naive_now
from app.db.models import Egg, PteroServer, PteroUser
from app.db.models.billing import BillingOrder, BillingOrderEffect, BillingPlan
from app.db.repositories.servers import server_repository
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
from app.core.contracts import ErrorInfo, OperationResult
from app.services.billing._ids import gen_order_no
from app.services.billing.plan_snapshot import build_plan_snapshot
from app.services.email import get_email_delay, get_site_url, load_template, render_template_body, send_email
from app.services.server_engine import (
    ServerBuildPatch,
    ServerEngineError,
    hooks as server_hooks,
    server_engine,
)

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
        server.plan_id
        for server in servers
        if server.plan_id is not None
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
        meta_plan_id = server.plan_id
        plan_obj = plans.get(meta_plan_id) if meta_plan_id is not None else None
        is_trial = bool(server.is_trial)
        items.append(
            ServerListItem(
                pteroId=server.id,
                uuid=server.uuid,
                name=server.name,
                ownerId=server.owner_id,
                ownerUsername=server.owner.username if server.owner else None,
                ownerEmail=server.owner.email if server.owner else None,
                eggName=egg_names.get(server.egg_id),
                expirationDate=expiration_date.isoformat() if expiration_date else None,
                daysLeft=days_left,
                statusLabel=status_label,
                isSuspended=server.is_suspended,
                isTrial=is_trial,
                planId=meta_plan_id,
                planCode=plan_obj.code if plan_obj else None,
                planName=plan_obj.display_name if plan_obj else None,
                planType=plan_obj.plan_type if plan_obj else None,
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
    today = await _get_today(db)
    expiration_date = today + timedelta(days=payload.expiration_days)

    # Validate channel-order attribution rules
    if payload.channel in ("taobao", "xianyu"):
        if payload.plan_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="电商渠道开通必须选择套餐",
            )
        if not (payload.external_order_id or "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="电商渠道开通必须填写外部订单号",
            )
        if payload.amount_yuan is None or payload.amount_yuan <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="电商渠道开通必须填写大于 0 的有效金额",
            )
        # 幂等检查：防止同一外部订单号重复创建服务器
        ext_id = (payload.external_order_id or "").strip()
        dup_order = (
            await db.execute(
                select(BillingOrder.order_no)
                .where(
                    BillingOrder.channel == payload.channel,
                    BillingOrder.external_order_id == ext_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if dup_order:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"外部订单号 '{ext_id}' 已在订单 #{dup_order} 中录入，请勿重复使用",
            )

    plan_obj: BillingPlan | None = None
    if payload.plan_id is not None:
        plan_obj = await db.get(BillingPlan, payload.plan_id)
        if plan_obj is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"套餐 {payload.plan_id} 不存在",
            )

    plan_snapshot: dict[str, Any] | None = None
    total_fen = 0
    if plan_obj is not None:
        amount_yuan = payload.amount_yuan if payload.amount_yuan is not None else (plan_obj.price_fen / 100)
        total_fen = int(round(amount_yuan * 100))
        plan_snapshot = build_plan_snapshot(
            plan_obj,
            total_fen=total_fen,
            total_days=payload.expiration_days,
        )

    await db.commit()

    created = await server_engine.create_server(
        db,
        owner_id=payload.user_id,
        node_id=payload.node_id,
        allocation_id=payload.allocation_id,
        egg_id=payload.egg_id,
        name=payload.server_name.strip(),
        description="",
        image=payload.docker_image.strip(),
        startup=payload.startup_command.strip(),
        environment=payload.environment,
        cpu=payload.cpu,
        memory=payload.memory,
        disk=payload.disk,
        database_limit=payload.databases,
        backup_limit=payload.backups,
        allocation_limit=payload.allocations,
        expiration_date=expiration_date,
        plan_id=payload.plan_id,
        is_trial=bool(plan_obj is not None and plan_obj.plan_type == "trial"),
        plan_snapshot=plan_snapshot,
    )

    server_id = int(created.id)

    try:
        # Generate BillingOrder for e-commerce channels
        if payload.channel in ("taobao", "xianyu") and payload.plan_id is not None and plan_obj is not None:
            order_no = gen_order_no()
            order = BillingOrder(
                order_no=order_no,
                user_id=payload.user_id,
                plan_id=payload.plan_id,
                plan_snapshot=plan_snapshot or build_plan_snapshot(plan_obj, total_fen=total_fen, total_days=payload.expiration_days),
                kind="new_purchase",
                channel=payload.channel,
                external_order_id=payload.external_order_id.strip() if payload.external_order_id else None,
                operator=actor_username,
                channel_note=payload.channel_note.strip() if payload.channel_note else None,
                period_count=1,
                discount_pct=Decimal("0"),
                total_fen=total_fen,
                total_days=payload.expiration_days,
                target_server_id=server_id,
                status="applied",
                received_fen=total_fen,
                applied_at=utc_naive_now(),
            )
            db.add(order)
            await db.flush()

            effect = BillingOrderEffect(
                order_id=order.id,
                server_id=server_id,
                effect_type="new_purchase",
                days=payload.expiration_days,
                prev_expiration_date=None,
                new_expiration_date=expiration_date,
                effect_committed_at=utc_naive_now(),
                post_actions_done_at=utc_naive_now(),
            )
            db.add(effect)

            await db.execute(
                update(PteroServer)
                .where(PteroServer.id == server_id)
                .values(external_id=f"order:{order.id}")
            )
            await db.commit()

        if created.warnings:
            await log_manager_activity(
                db,
                actor=actor_username,
                category="server",
                operation=OperationResult(
                    action="llm.provision",
                    phase="execution",
                    outcome="failed",
                    target={"server_id": server_id},
                    facts={"server_created": True},
                    error=ErrorInfo(code="dependency.failed", detail="; ".join(created.warnings)[:200]),
                ),
                detail_key="create_server_partial",
                detail_params={
                    "actor": actor_username,
                    "server_name": payload.server_name,
                    "server_id": server_id,
                    "llm_error": "; ".join(created.warnings)[:200],
                },
            )
    except Exception as exc:
        await db.rollback()
        cleanup_succeeded = False
        try:
            await server_engine.delete_server(db, server_id)
            cleanup_succeeded = True
        except ServerEngineError:
            await db.rollback()
            logger.exception("Failed to clean up server %s after local persistence failure", server_id)

        logger.exception("Failed to persist manager metadata for server %s", server_id)
        detail = "服务器已创建，但写入管理元数据失败"
        if cleanup_succeeded:
            detail += "，已自动回滚"
        else:
            detail += "，且自动回滚失败，请检查节点与服务器状态"
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

    log_params: dict[str, Any] = {
        "actor": actor_username,
        "server_name": payload.server_name,
        "server_id": server_id,
        "channel": payload.channel,
    }
    if payload.external_order_id:
        log_params["external_order_id"] = payload.external_order_id
    if payload.amount_yuan is not None:
        log_params["amount_yuan"] = payload.amount_yuan

    await log_manager_activity(
        db,
        actor=actor_username,
        category="server",
        detail_key="create_server",
        operation=OperationResult(action="server.create", phase="execution", outcome="success", target={"server_id": server_id}),
        detail_params=log_params,
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

    raw_date = payload.date.strip() if isinstance(payload.date, str) else payload.date
    new_date: date | None
    if not raw_date:
        # Clear expiration → server becomes "permanent". Do not auto-unsuspend
        # (suspended-for-other-reasons must remain suspended; admin decides).
        new_date = None
    else:
        try:
            new_date = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="日期格式无效，请使用 YYYY-MM-DD") from exc

    # 1. 检查试用状态与确定有效套餐
    is_trial = bool(server.is_trial)
    meta_plan_id = server.plan_id
    plan_obj: BillingPlan | None = None
    if meta_plan_id is not None:
        plan_obj = await db.get(BillingPlan, meta_plan_id)

    effective_plan: BillingPlan | None = None
    order_kind = "renew"
    effect_type = "renew"

    if is_trial:
        order_kind = "convert"
        effect_type = "convert"
        if plan_obj is not None and plan_obj.plan_type == "trial":
            if plan_obj.linked_plan_id is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="绑定的试用套餐未配置关联标准套餐，无法执行试用转正",
                )
            linked_plan = await db.get(BillingPlan, plan_obj.linked_plan_id)
            if linked_plan is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"关联的标准套餐 (ID: {plan_obj.linked_plan_id}) 不存在",
                )
            effective_plan = linked_plan
        elif plan_obj is not None and plan_obj.plan_type == "standard":
            effective_plan = plan_obj
    else:
        effective_plan = plan_obj

    # 2. 校验电商渠道规则与幂等性
    ext_id = (payload.external_order_id or "").strip()
    if payload.channel in ("taobao", "xianyu"):
        if new_date is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="电商渠道续期必须指定具体到期日",
            )
        if effective_plan is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="该服务器未绑定有效套餐，无法生成电商订单，请选择“其他”来源或先绑定套餐",
            )
        if not ext_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="电商渠道续期必须填写外部订单号",
            )
        if payload.amount_yuan is None or payload.amount_yuan <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="电商渠道续期必须填写大于 0 的有效金额",
            )
        # 幂等检查：防止跨服务器盗用/重用外部订单号；同服务器重试支持幂等自愈后置动作
        existing_order = (
            await db.execute(
                select(BillingOrder)
                .where(
                    BillingOrder.channel == payload.channel,
                    BillingOrder.external_order_id == ext_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()

        if existing_order:
            if existing_order.target_server_id != server_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"外部订单号 '{ext_id}' 已在订单 #{existing_order.order_no} 中录入，请勿重复使用",
                )
            # 同一服务器同一外部单号的重试请求：检查 effect.post_actions_done_at
            existing_effect = await db.get(BillingOrderEffect, existing_order.id)
            if existing_effect and existing_effect.post_actions_done_at is None:
                # 上次后置动作（如解冻）失败了，尝试重新执行后置动作
                post_retry_err: Exception | None = None
                try:
                    if existing_effect.new_expiration_date is not None and was_suspended:
                        await server_engine.unsuspend_server(db, server_id, actor=actor_username)
                except Exception as exc:
                    post_retry_err = exc

                if post_retry_err is None:
                    existing_effect.post_actions_done_at = utc_naive_now()
                    await db.commit()
                    return MessageResponse(
                        message=f"服务器 {server_name} 续期成功，节点解冻与同步已恢复（订单 #{existing_order.order_no}）"
                    )
                else:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"订单 #{existing_order.order_no} 已记录，但重试节点同步/解冻失败: {post_retry_err}，请稍后再试",
                    )
            return MessageResponse(
                message=f"服务器 {server_name} 续期成功（已存在订单 #{existing_order.order_no}）"
            )

    # 3. 试用转正先幂等同步容器规格（失败则回滚规格并直接中止，绝不落单或改到期日）
    today = await _get_today(db)
    convert_plan_id = effective_plan.id if (is_trial and effective_plan is not None) else None
    is_ecommerce = payload.channel in ("taobao", "xianyu") and new_date is not None and effective_plan is not None

    if convert_plan_id is not None and effective_plan is not None:
        await server_engine.update_build(
            db,
            server_id,
            ServerBuildPatch.from_plan(effective_plan),
        )

    # 4. Step 1: 单事务加 FOR UPDATE 锁读取到期日/停机态、写入订单与服务器状态并原子提交
    locked_server = await db.scalar(
        select(PteroServer)
        .where(PteroServer.id == server_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_server is None:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="服务器不存在")

    old_expiration_date = locked_server.expiration_date
    was_suspended = locked_server.is_suspended
    owner_id = int(locked_server.owner_id)
    base_date = old_expiration_date if (old_expiration_date and old_expiration_date >= today) else today
    added_days = max(1, (new_date - base_date).days) if new_date is not None else 30
    amount_yuan = payload.amount_yuan if payload.amount_yuan is not None else (
        (effective_plan.price_fen / 100) if effective_plan else 0
    )
    total_fen = int(round(amount_yuan * 100))

    snap: dict[str, Any] = {}
    if effective_plan is not None:
        snap = build_plan_snapshot(effective_plan, total_fen=total_fen, total_days=added_days)

    created_order_id: int | None = None
    if is_ecommerce and effective_plan is not None:
        order_no = gen_order_no()
        order = BillingOrder(
            order_no=order_no,
            user_id=owner_id,
            plan_id=effective_plan.id,
            plan_snapshot=snap,
            kind=order_kind,
            channel=payload.channel,
            external_order_id=payload.external_order_id.strip() if payload.external_order_id else None,
            operator=actor_username,
            channel_note=payload.channel_note.strip() if payload.channel_note else None,
            period_count=1,
            discount_pct=Decimal("0"),
            total_fen=total_fen,
            total_days=added_days,
            target_server_id=server_id,
            status="applied",
            received_fen=total_fen,
            applied_at=utc_naive_now(),
        )
        db.add(order)
        await db.flush()
        created_order_id = order.id

        effect = BillingOrderEffect(
            order_id=order.id,
            server_id=server_id,
            effect_type=effect_type,
            days=added_days,
            prev_expiration_date=old_expiration_date,
            new_expiration_date=new_date,
            effect_committed_at=utc_naive_now(),
            post_actions_done_at=None,
        )
        db.add(effect)

    await server_engine.renew_server(
        db,
        server_id,
        new_expiration_date=new_date,
        auto_unsuspend=False,
        convert_plan_id=convert_plan_id,
        convert_build=None,
        sync_llm=False,
        actor=actor_username,
    )

    # 5. Step 2: 外部后置动作（先解冻 + 实时恢复 LLM，再按需执行转正套餐 LLM 同步/自动吊销）
    post_action_error: Exception | None = None
    if new_date is not None and was_suspended:
        try:
            await server_engine.unsuspend_server(db, server_id, actor=actor_username)
        except Exception as exc:
            post_action_error = exc
            logger.warning("Failed to unsuspend server %s on Wings: %s", server_id, exc)

    if convert_plan_id is not None:
        await server_hooks.on_plan_changed(db, server_id=server_id, new_snapshot=snap)

    if post_action_error is None:
        if created_order_id is not None:
            try:
                await db.execute(
                    update(BillingOrderEffect)
                    .where(BillingOrderEffect.order_id == created_order_id)
                    .values(post_actions_done_at=utc_naive_now())
                )
                await db.commit()
            except Exception:
                logger.warning("Failed to mark post_actions_done_at for order %s", created_order_id)
    else:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"服务器到期日已更新，但节点同步/解冻失败: {post_action_error}，请重试",
        )

    log_params: dict[str, Any] = {
        "actor": actor_username,
        "server_name": server_name,
        "server_id": server_id,
        "channel": payload.channel,
    }
    if new_date is not None:
        log_params["date"] = new_date.isoformat()
    if payload.external_order_id:
        log_params["external_order_id"] = payload.external_order_id
    if payload.amount_yuan is not None:
        log_params["amount_yuan"] = payload.amount_yuan

    if new_date is None:
        await log_manager_activity(
            db,
            actor=actor_username,
            category="server",
            detail_key="set_server_permanent",
            operation=OperationResult(action="server.set_permanent", phase="execution", outcome="success", target={"server_id": server_id}),
            detail_params=log_params,
        )
        return MessageResponse(message=f"已将 {server_name} 设为永久")

    await log_manager_activity(
        db,
        actor=actor_username,
        category="server",
        detail_key="renew_server",
        operation=OperationResult(action="server.renew", phase="execution", outcome="success", target={"server_id": server_id}),
        detail_params=log_params,
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

    if was_suspended:
        await server_engine.unsuspend_server(db, server_id, actor=current_user.username)
    else:
        await server_engine.suspend_server(db, server_id, actor=current_user.username)

    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        detail_key="unsuspend_server" if was_suspended else "suspend_server",
        operation=OperationResult(action="server.unsuspend" if was_suspended else "server.suspend", phase="execution", outcome="success", target={"server_id": server_id}),
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
                    await server_engine.suspend_server(db, server_id, actor=actor_username)
                else:
                    await server_engine.unsuspend_server(db, server_id, actor=actor_username)
                success += 1
            except ServerEngineError:
                await db.rollback()
                errors += 1

        operation = batch_operation(f"server.batch.{action}", {"requested_server_ids": server_ids}, success, errors)
        await log_manager_activity(
            db,
            actor=actor_username,
            category="server",
            detail_key=f"batch_{action}",
            operation=operation,
            detail_params={"success": success, "failed": errors},
        )
        return BatchServersResponse(
            operation=operation,
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
            .where(PteroServer.id.in_(server_ids))
            .order_by(PteroServer.id.asc())
        )
        servers = list(rows.scalars().all())
        await db.commit()

        for server in servers:
            old_expiration_date = server.expiration_date
            base_date = today if old_expiration_date and old_expiration_date < today else (old_expiration_date or today)
            new_date = base_date + timedelta(days=payload.days)
            try:
                # 批量续期按产品约定允许直接延长试用服到期日；engine 先写新到期日再自动解冻
                await server_engine.renew_server(
                    db,
                    server.id,
                    new_expiration_date=new_date,
                    auto_unsuspend=True,
                    actor=actor_username,
                )
                success += 1
            except ServerEngineError:
                await db.rollback()
                errors += 1

        operation = batch_operation(f"server.batch.{action}", {"requested_server_ids": server_ids}, success, errors)
        await log_manager_activity(
            db,
            actor=actor_username,
            category="server",
            detail_key="batch_renew",
            operation=operation,
            detail_params={"success": success, "failed": errors},
        )
        return BatchServersResponse(
            operation=operation,
            message=f"操作完成：成功 {success}，失败 {errors}",
            success=success,
            failed=errors,
        )

    if action == "delete":
        for server_id in server_ids:
            try:
                await server_engine.delete_server(db, server_id)
                success += 1
            except ServerEngineError:
                await db.rollback()
                errors += 1

        operation = batch_operation(f"server.batch.{action}", {"requested_server_ids": server_ids}, success, errors)
        await log_manager_activity(
            db,
            actor=actor_username,
            category="server",
            detail_key="batch_delete",
            operation=operation,
            detail_params={"success": success, "failed": errors},
        )
        return BatchServersResponse(
            operation=operation,
            message=f"操作完成：成功 {success}，失败 {errors}",
            success=success,
            failed=errors,
        )

    if action == "update_plan":
        new_plan_id = payload.planId
        new_plan: BillingPlan | None = None
        if new_plan_id is not None:
            new_plan = await db.get(BillingPlan, new_plan_id)
            if new_plan is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="套餐不存在")

        rows = await db.execute(
            select(PteroServer)
            .where(PteroServer.id.in_(server_ids))
            .order_by(PteroServer.id.asc())
        )
        servers = list(rows.scalars().all())
        old_plan_ids = {s.plan_id for s in servers if s.plan_id is not None}
        old_plans: dict[int, BillingPlan] = {}
        if old_plan_ids:
            old_plan_rows = await db.execute(select(BillingPlan).where(BillingPlan.id.in_(old_plan_ids)))
            old_plans = {p.id: p for p in old_plan_rows.scalars().all()}

        for server in servers:
            old_plan = old_plans.get(server.plan_id) if server.plan_id is not None else None
            server_name = server.name
            server_id = int(server.id)
            try:
                await server_engine.apply_plan_transition(
                    db,
                    server_id,
                    new_plan_id=new_plan_id,
                    sync_llm=False,
                    actor=actor_username,
                )
                await log_manager_activity(
                    db,
                    actor=actor_username,
                    category="server",
                    detail_key="admin_server.plan.update",
                    operation=OperationResult(action="server.plan.update", phase="execution", outcome="success", target={"server_id": server_id}),
                    detail_params={
                        "server_name": server_name,
                        "server_id": server_id,
                        "old_plan": old_plan.display_name if old_plan else "—",
                        "new_plan": new_plan.display_name if new_plan else "—",
                    },
                )
                success += 1
            except Exception:
                await db.rollback()
                errors += 1
                logger.exception("Failed to update plan for server %s", server_id)

        return BatchServersResponse(
            operation=batch_operation(f"server.batch.{action}", {"requested_server_ids": server_ids}, success, errors),
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
        .options(selectinload(PteroServer.owner))
        .where(PteroServer.id.in_(server_ids))
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

    operation = batch_operation(f"server.batch.{action}", {"requested_server_ids": server_ids}, success, errors)
    await log_manager_activity(
        db,
        actor=actor_username,
        category="server",
        detail_key="batch_email",
        operation=operation,
        detail_params={"success": success, "failed": errors},
    )
    return BatchServersResponse(
        operation=operation,
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
    server_name = server.name
    await server_engine.delete_server(db, server_id, force=force)

    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        detail_key="delete_server",
        operation=OperationResult(action="server.delete", phase="execution", outcome="success", target={"server_id": server_id}),
        detail_params={"actor": current_user.username, "server_name": server_name, "server_id": server_id},
    )
    if force:
        return MessageResponse(message=f"服务器 '{server_name}' 已强制删除")
    return MessageResponse(message=f"服务器 '{server_name}' 已删除")


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
    if not payload.expirationDate:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无有效更新内容")

    try:
        new_date = date.fromisoformat(payload.expirationDate)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="日期格式无效") from exc

    await server_engine.renew_server(
        db,
        server_id,
        new_expiration_date=new_date,
        auto_unsuspend=False,
        actor=actor_username,
    )
    await log_manager_activity(
        db,
        actor=actor_username,
        category="server",
        detail_key="set_expiry",
        operation=OperationResult(action="server.expiry.update", phase="execution", outcome="success", target={"server_id": server_id}),
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

    old_plan = await db.get(BillingPlan, server.plan_id) if server.plan_id is not None else None
    new_plan: BillingPlan | None = None
    if payload.planId is not None:
        new_plan = await db.get(BillingPlan, payload.planId)
        if new_plan is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="套餐不存在")

    server_name = server.name
    await server_engine.apply_plan_transition(
        db,
        server_id,
        new_plan_id=payload.planId,
        sync_llm=False,
        actor=current_user.username,
    )

    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        detail_key="admin_server.plan.update",
        operation=OperationResult(action="server.plan.update", phase="execution", outcome="success", target={"server_id": server_id}),
        detail_params={
            "server_name": server_name,
            "server_id": server_id,
            "old_plan": old_plan.display_name if old_plan else "—",
            "new_plan": new_plan.display_name if new_plan else "—",
        },
    )
    return MessageResponse(message="套餐绑定已更新")
