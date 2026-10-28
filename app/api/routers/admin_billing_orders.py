"""Admin routes for billing orders — see ``BILLING_DESIGN.md`` §11.

Mounted under ``/api`` (so the full prefix is ``/api/admin/billing/orders``).

Read endpoints:

* ``GET    /admin/billing/orders``       — list (filterable)
* ``GET    /admin/billing/orders/{id}``  — detail (incl. invoices/transactions/effect/refunds)

Action endpoints (§11.2 capability matrix):

* ``POST   /admin/billing/orders/{id}/refund``
* ``POST   /admin/billing/orders/{id}/force-apply``
* ``POST   /admin/billing/orders/{id}/force-close``
* ``POST   /admin/billing/orders/{id}/cleanup-placeholder``
"""

from __future__ import annotations
from fastapi import Response
from app.core.api_errors import ApiError
from app.core.contracts import ErrorInfo, OperationResult
from app.core.operation import set_operation

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.time import to_iso_z
from app.db.models.billing import (
    BillingInvoice,
    BillingInvoiceTransaction,
    BillingOrder,
    BillingOrderEffect,
    BillingRefund,
)
from app.db.models.pterodactyl import PteroServer, PteroUser
from app.schemas.billing_admin_orders import (
    ActionAck,
    AdminInvoiceOut,
    AdminOrderListItem,
    AdminOrderOut,
    CleanupPlaceholderRequest,
    ForceApplyRequest,
    ForceCloseRequest,
    OrderEffectOut,
    OrderListResponse,
    OrderRefundSummary,
    OrderTransactionOut,
)
from app.schemas.billing_refunds import RefundCreateRequest, RefundOut
from app.services.audit import log_manager_activity
from app.services.billing import admin_actions, payments, refunds
from app.services.billing.gateway_client import GatewayError

router = APIRouter(prefix="/admin/billing/orders", tags=["billing"])


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #


def _ts(dt) -> str | None:
    return to_iso_z(dt) if dt else None


def _list_item(
    order: BillingOrder,
    owner_username: str | None = None,
    target_server_name: str | None = None,
) -> AdminOrderListItem:
    snap = order.plan_snapshot
    return AdminOrderListItem(
        id=order.id,
        order_no=order.order_no,
        user_id=order.user_id,
        owner_username=owner_username,
        plan_id=order.plan_id,
        plan_code=snap["plan_code"],
        plan_name=snap["plan_name"],
        kind=order.kind,
        channel=order.channel,
        external_order_id=order.external_order_id,
        operator=order.operator,
        channel_note=order.channel_note,
        period_count=order.period_count,
        total_fen=order.total_fen,
        total_days=order.total_days,
        target_server_id=order.target_server_id,
        target_server_name=target_server_name,
        status=order.status,
        received_fen=order.received_fen,
        refunded_fen=order.refunded_fen,
        created_at=to_iso_z(order.created_at),
        updated_at=to_iso_z(order.updated_at),
    )


def _serialize_invoice(invoice: BillingInvoice) -> AdminInvoiceOut:
    return AdminInvoiceOut(
        id=invoice.id,
        invoice_no=invoice.invoice_no,
        status=invoice.status,
        total_fen=invoice.total_fen,
        currency_code=invoice.currency_code,
        due_at=_ts(invoice.due_at),
        paid_at=_ts(invoice.paid_at),
        gateway_code=payments.PAYMENT_CHANNELS[invoice.gateway_code] if invoice.gateway_code is not None else None,
        created_at=to_iso_z(invoice.created_at),
        updated_at=to_iso_z(invoice.updated_at),
    )


def _serialize_transaction(tx: BillingInvoiceTransaction) -> OrderTransactionOut:
    return OrderTransactionOut(
        id=tx.id,
        invoice_id=tx.invoice_id,
        gateway_code=payments.PAYMENT_CHANNELS[tx.gateway_code],
        payment_id=tx.payment_id,
        transaction_id=tx.transaction_id,
        amount_fen=tx.amount_fen,
        refunded_fen=tx.refunded_fen,
        status=tx.status,
        created_at=to_iso_z(tx.created_at),
        updated_at=to_iso_z(tx.updated_at),
    )


def _serialize_effect(effect: BillingOrderEffect | None) -> OrderEffectOut | None:
    if effect is None:
        return None
    return OrderEffectOut(
        order_id=effect.order_id,
        effect_type=effect.effect_type,
        server_id=effect.server_id,
        days=effect.days,
        prev_expiration_date=(
            effect.prev_expiration_date.isoformat()
            if effect.prev_expiration_date
            else None
        ),
        new_expiration_date=effect.new_expiration_date.isoformat(),
        effect_committed_at=to_iso_z(effect.effect_committed_at),
        post_actions_done_at=_ts(effect.post_actions_done_at),
    )


def _serialize_refund_summary(
    refund: BillingRefund,
    initiated_by_username: str | None = None,
) -> OrderRefundSummary:
    return OrderRefundSummary(
        id=refund.id,
        refund_no=refund.refund_no,
        transaction_id=refund.transaction_id,
        payment_id=refund.payment_id,
        amount_fen=refund.amount_fen,
        status=refund.status,
        reason=refund.reason,
        gateway_refund_id=refund.gateway_refund_id,
        retry_count=refund.retry_count,
        last_error=refund.last_error,
        initiated_by=refund.initiated_by,
        initiated_by_username=initiated_by_username,
        created_at=to_iso_z(refund.created_at),
        updated_at=to_iso_z(refund.updated_at),
    )


def _serialize_refund(refund: BillingRefund) -> RefundOut:
    return RefundOut(
        id=refund.id,
        refund_no=refund.refund_no,
        transaction_id=refund.transaction_id,
        payment_id=refund.payment_id,
        order_id=refund.order_id,
        amount_fen=refund.amount_fen,
        status=refund.status,
        reason=refund.reason,
        gateway_refund_id=refund.gateway_refund_id,
        retry_count=refund.retry_count,
        last_error=refund.last_error,
        initiated_by=refund.initiated_by,
        created_at=to_iso_z(refund.created_at),
        updated_at=to_iso_z(refund.updated_at),
    )


# --------------------------------------------------------------------------- #
# List / detail
# --------------------------------------------------------------------------- #


@router.get("", response_model=OrderListResponse)
async def list_orders_endpoint(
    status_filter: str | None = Query(None, alias="status", max_length=32),
    channel_filter: str | None = Query(None, alias="channel", max_length=32),
    user_id: int | None = Query(None, gt=0),
    kind: str | None = Query(None, pattern=r"^(renew|new_purchase|upgrade|convert)$"),
    q: str | None = Query(
        None,
        max_length=64,
        description="模糊搜索：订单号/外部订单号/订单ID/用户名/邮箱/用户UUID/服务器名/服务器ID/服务器UUID/服务器短UUID/发票号/渠道交易号",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> OrderListResponse:
    stmt = select(BillingOrder)
    count_stmt = select(func.count(BillingOrder.id))
    if status_filter:
        stmt = stmt.where(BillingOrder.status == status_filter)
        count_stmt = count_stmt.where(BillingOrder.status == status_filter)
    if channel_filter:
        stmt = stmt.where(BillingOrder.channel == channel_filter)
        count_stmt = count_stmt.where(BillingOrder.channel == channel_filter)
    if user_id:
        stmt = stmt.where(BillingOrder.user_id == user_id)
        count_stmt = count_stmt.where(BillingOrder.user_id == user_id)
    if kind:
        stmt = stmt.where(BillingOrder.kind == kind)
        count_stmt = count_stmt.where(BillingOrder.kind == kind)
    if q:
        token = q.strip()
        if token:
            needle = f"%{token}%"

            inv_subq = select(BillingInvoice.order_id).where(
                BillingInvoice.invoice_no.ilike(needle)
            )

            # 子查询：网关交易号命中 invoice -> order_id 集合
            tx_subq = (
                select(BillingInvoice.order_id)
                .join(
                    BillingInvoiceTransaction,
                    BillingInvoiceTransaction.invoice_id == BillingInvoice.id,
                )
                .where(BillingInvoiceTransaction.transaction_id.ilike(needle))
            )

            # 主表条件：直接字段模糊匹配，或经 outerjoin 用户/服务器匹配，或命中发票/交易子查询
            direct_or = or_(
                BillingOrder.order_no.ilike(needle),
                BillingOrder.external_order_id.ilike(needle),
                cast(BillingOrder.id, String).ilike(needle),
                cast(BillingOrder.user_id, String).ilike(needle),
                cast(BillingOrder.target_server_id, String).ilike(needle),
                BillingOrder.id.in_(inv_subq),
                BillingOrder.id.in_(tx_subq),
            )

            # 用 outerjoin 到 users / servers 表实现用户名/邮箱/UUID、
            # 服务器名/UUID/短UUID 的模糊匹配。
            stmt = (
                stmt.outerjoin(PteroUser, PteroUser.id == BillingOrder.user_id)
                .outerjoin(
                    PteroServer,
                    PteroServer.id == BillingOrder.target_server_id,
                )
                .where(
                    or_(
                        direct_or,
                        PteroUser.username.ilike(needle),
                        PteroUser.email.ilike(needle),
                        PteroUser.uuid.ilike(needle),
                        PteroServer.name.ilike(needle),
                        PteroServer.uuid.ilike(needle),
                        PteroServer.uuid_short.ilike(needle),
                    )
                )
            )
            count_stmt = (
                count_stmt.outerjoin(PteroUser, PteroUser.id == BillingOrder.user_id)
                .outerjoin(
                    PteroServer,
                    PteroServer.id == BillingOrder.target_server_id,
                )
                .where(
                    or_(
                        direct_or,
                        PteroUser.username.ilike(needle),
                        PteroUser.email.ilike(needle),
                        PteroUser.uuid.ilike(needle),
                        PteroServer.name.ilike(needle),
                        PteroServer.uuid.ilike(needle),
                        PteroServer.uuid_short.ilike(needle),
                    )
                )
            )
    stmt = stmt.order_by(BillingOrder.id.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    total = int(await db.scalar(count_stmt) or 0)

    # Bulk resolve usernames and server names
    user_ids = {o.user_id for o in rows}
    usernames: dict[int, str] = {}
    if user_ids:
        from app.db.models.pterodactyl import PteroUser as _U
        user_rows = await db.execute(
            select(_U.id, _U.username).where(_U.id.in_(user_ids))
        )
        usernames = {uid: uname for uid, uname in user_rows.all()}

    server_ids = {o.target_server_id for o in rows if o.target_server_id is not None}
    server_names: dict[int, str] = {}
    if server_ids:
        from app.db.models.pterodactyl import PteroServer as _S
        srv_rows = await db.execute(
            select(_S.id, _S.name).where(_S.id.in_(server_ids))
        )
        server_names = {sid: sname for sid, sname in srv_rows.all()}

    return OrderListResponse(
        items=[
            _list_item(
                o,
                owner_username=usernames.get(o.user_id),
                target_server_name=server_names.get(o.target_server_id) if o.target_server_id is not None else None,
            )
            for o in rows
        ],
        total=total,
    )


@router.get("/{order_id}", response_model=AdminOrderOut)
async def get_order_endpoint(
    order_id: int,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminOrderOut:
    order = await db.scalar(
        select(BillingOrder).where(BillingOrder.id == order_id)
    )
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="订单不存在")

    invoices = (
        await db.execute(
            select(BillingInvoice)
            .where(BillingInvoice.order_id == order_id)
            .order_by(BillingInvoice.id.asc())
        )
    ).scalars().all()
    invoice_ids = [inv.id for inv in invoices]

    txs: list[BillingInvoiceTransaction] = []
    if invoice_ids:
        tx_rows = await db.execute(
            select(BillingInvoiceTransaction)
            .where(BillingInvoiceTransaction.invoice_id.in_(invoice_ids))
            .order_by(BillingInvoiceTransaction.id.asc())
        )
        txs = list(tx_rows.scalars().all())

    effect = await db.scalar(
        select(BillingOrderEffect).where(BillingOrderEffect.order_id == order_id)
    )

    refund_rows = (
        await db.execute(
            select(BillingRefund)
            .where(BillingRefund.order_id == order_id)
            .order_by(BillingRefund.id.asc())
        )
    ).scalars().all()

    # Resolve owner username and server name
    owner_username: str | None = None
    target_server_name: str | None = None
    if order.user_id:
        from app.db.models.pterodactyl import PteroUser as _U
        owner_username = await db.scalar(select(_U.username).where(_U.id == order.user_id))
    if order.target_server_id is not None:
        from app.db.models.pterodactyl import PteroServer as _S
        target_server_name = await db.scalar(select(_S.name).where(_S.id == order.target_server_id))

    # Resolve admin usernames for refund initiated_by
    admin_ids = {r.initiated_by for r in refund_rows if r.initiated_by is not None}
    admin_names: dict[int, str] = {}
    if admin_ids:
        from app.db.models.pterodactyl import PteroUser as _U
        admin_rows = await db.execute(select(_U.id, _U.username).where(_U.id.in_(admin_ids)))
        admin_names = {uid: uname for uid, uname in admin_rows.all()}

    return AdminOrderOut(
        id=order.id,
        order_no=order.order_no,
        user_id=order.user_id,
        owner_username=owner_username,
        plan_id=order.plan_id,
        plan_snapshot=order.plan_snapshot,
        kind=order.kind,
        channel=order.channel,
        external_order_id=order.external_order_id,
        operator=order.operator,
        channel_note=order.channel_note,
        period_count=order.period_count,
        discount_pct=float(order.discount_pct),
        total_fen=order.total_fen,
        total_days=order.total_days,
        target_server_id=order.target_server_id,
        target_server_name=target_server_name,
        reserved_node_id=order.reserved_node_id,
        reserved_allocation_id=order.reserved_allocation_id,
        status=order.status,
        received_fen=order.received_fen,
        refunded_fen=order.refunded_fen,
        apply_retry_count=order.apply_retry_count,
        next_apply_at=_ts(order.next_apply_at),
        last_apply_error=order.last_apply_error,
        applied_at=_ts(order.applied_at),
        closed_at=_ts(order.closed_at),
        cancelled_at=_ts(order.cancelled_at),
        created_at=to_iso_z(order.created_at),
        updated_at=to_iso_z(order.updated_at),
        invoices=[_serialize_invoice(inv) for inv in invoices],
        transactions=[_serialize_transaction(tx) for tx in txs],
        effect=_serialize_effect(effect),
        refunds=[
            _serialize_refund_summary(
                r,
                initiated_by_username=admin_names.get(r.initiated_by) if r.initiated_by is not None else None,
            )
            for r in refund_rows
        ],
    )


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #


@router.post(
    "/{order_id}/refund",
    response_model=RefundOut,
    status_code=status.HTTP_201_CREATED,
)
async def refund_order_endpoint(
    order_id: int,
    payload: RefundCreateRequest,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RefundOut:
    try:
        refund = await refunds.initiate_refund(
            db,
            order_id=order_id,
            transaction_id=payload.transaction_id,
            reason=payload.reason,
            admin_id=admin.id,
        )
    except refunds.CannotRefund as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except GatewayError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    await log_manager_activity(
        db,
        actor=admin.username,
        category="billing",
        detail_key="billing.order.refund_initiated",
        operation=OperationResult(action="billing.refund.initiate", phase="acceptance", outcome="success", target={"order_id": order_id, "refund_id": refund.id}),
        detail_params={
            "order_id": order_id,
            "refund_id": refund.id,
            "amount_fen": refund.amount_fen,
        },
    )
    return _serialize_refund(refund)


@router.post(
    "/{order_id}/refunds/{refund_id}/reconcile",
    response_model=RefundOut,
)
async def reconcile_refund_endpoint(
    order_id: int,
    refund_id: int,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RefundOut:
    """查询原退款；明确失败的退款由新请求重新申请。"""
    refund = await db.scalar(
        select(BillingRefund).where(BillingRefund.id == refund_id)
    )
    if refund is None or refund.order_id != order_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="退款记录不存在")
    try:
        outcome = await refunds.reconcile_refund_once(db, refund_id, query_channel=True)
    except refunds.CannotRefund as exc:
        raise HTTPException(409, str(exc)) from exc
    except GatewayError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    refund = await db.scalar(
        select(BillingRefund).where(BillingRefund.id == refund_id)
    )
    await log_manager_activity(
        db,
        actor=admin.username,
        category="billing",
        detail_key="billing.order.refund_reconciled",
        operation=OperationResult(action="billing.refund.reconcile", phase="execution", outcome="failed" if outcome in {"failed", "exhausted"} else "success", target={"order_id": order_id, "refund_id": refund_id}, facts={"result": outcome}),
        detail_params={
            "order_id": order_id,
            "refund_id": refund_id,
            "outcome": outcome,
        },
    )
    return _serialize_refund(refund)


@router.post(
    "/{order_id}/force-apply",
    response_model=ActionAck,
    responses={202: {
        "model": ActionAck,
        "description": "已保存重试安排，Location 指向订单查询地址",
        "headers": {"Location": {"description": "订单查询地址", "schema": {"type": "string"}}},
    }},
)
async def force_apply_endpoint(
    order_id: int,
    response: Response,
    _payload: ForceApplyRequest = ForceApplyRequest(),
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ActionAck:
    try:
        result = await admin_actions.force_apply(db, order_id, admin_id=admin.id)
    except admin_actions.OrderNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except admin_actions.CannotForceApply as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    error = None
    if result.value == "retry_scheduled":
        operation = OperationResult(action="billing.order.apply", phase="acceptance", outcome="success", target={"order_id": order_id})
    elif result.value == "applied":
        operation = OperationResult(action="billing.order.apply", phase="execution", outcome="success", target={"order_id": order_id})
    else:
        error = ErrorInfo(code="billing.order.apply_failed" if result.value == "permanent_failure" else "resource.conflict")
        operation = OperationResult(action="billing.order.apply", phase="execution", outcome="failed", target={"order_id": order_id}, error=error)
    set_operation(operation)
    await log_manager_activity(
        db,
        actor=admin.username,
        category="billing",
        detail_key="billing.order.force_applied",
        detail_params={"order_id": order_id, "result": result.value},
        operation=operation,
    )
    if result.value == "retry_scheduled":
        response.status_code = 202
        response.headers["Location"] = f"/api/admin/billing/orders/{order_id}"
    if error is not None:
        raise ApiError(502 if result.value == "permanent_failure" else 409, error.code, operation=operation, context={"result": result.value})
    return ActionAck(order_id=order_id, action="force_apply", result=result.value)


@router.post("/{order_id}/force-close", response_model=ActionAck)
async def force_close_endpoint(
    order_id: int,
    payload: ForceCloseRequest,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ActionAck:
    try:
        await admin_actions.force_close(
            db, order_id, admin_id=admin.id, note=payload.note
        )
    except admin_actions.OrderNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except admin_actions.CannotForceClose as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await log_manager_activity(
        db,
        actor=admin.username,
        category="billing",
        detail_key="billing.order.force_closed",
        operation=OperationResult(action="billing.order.close", phase="execution", outcome="success", target={"order_id": order_id}),
        detail_params={"order_id": order_id, "note": payload.note},
    )
    return ActionAck(order_id=order_id, action="force_close", result="ok")


@router.post("/{order_id}/cleanup-placeholder", response_model=ActionAck)
async def cleanup_placeholder_endpoint(
    order_id: int,
    _payload: CleanupPlaceholderRequest = CleanupPlaceholderRequest(),
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ActionAck:
    try:
        await admin_actions.cleanup_placeholder(db, order_id, admin_id=admin.id)
    except admin_actions.OrderNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except admin_actions.CannotCleanupPlaceholder as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await log_manager_activity(
        db,
        actor=admin.username,
        category="billing",
        detail_key="billing.order.placeholder_cleaned",
        operation=OperationResult(action="billing.order.placeholder_cleanup", phase="execution", outcome="success", target={"order_id": order_id}),
        detail_params={"order_id": order_id},
    )
    return ActionAck(order_id=order_id, action="cleanup_placeholder", result="ok")
