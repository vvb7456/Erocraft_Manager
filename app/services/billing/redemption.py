"""Redemption code batches, TXT exports, Agiso 91 custom pull API, and user redemption."""

from __future__ import annotations

import logging
import re
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import String, case, cast, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_errors import ApiError
from app.core.contracts import OperationResult
from app.core.runtime_settings import AUTOMATION_SPECS, BILLING_SPECS
from app.core.settings_store import get_settings_store
from app.core.time import local_today, to_iso_z, utc_naive_now
from app.db.models.billing import (
    BillingOrder,
    BillingOrderEffect,
    BillingPlan,
    RedemptionBatch,
    RedemptionCode,
    RedemptionExport,
)
from app.db.models.manager import ServerMeta
from app.db.models.pterodactyl import Allocation, PteroServer, PteroUser
from app.schemas.redemption import (
    AgisoCardItem,
    AgisoIssueData,
    AgisoIssueRequest,
    RedeemCompatibleServerOut,
    RedeemExecuteResponse,
    RedeemPlanSummaryOut,
    RedeemPreviewResponse,
    RedemptionBatchCreateRequest,
    RedemptionBatchDetailOut,
    RedemptionBatchListResponse,
    RedemptionBatchOut,
    RedemptionBatchVoidOut,
    RedemptionCodeListResponse,
    RedemptionCodeOut,
    RedemptionExportOut,
)
from app.services import server_lifecycle
from app.services.audit import log_manager_activity
from app.services.billing._ids import gen_order_no
from app.services.billing.apply_engine import _upsert_meta_expiration_plan_trial
from app.services.billing.orders import _build_snapshot
from app.services.server_lifecycle import LifecycleError, LifecycleValidationError

logger = logging.getLogger(__name__)

CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_STRIP_RE = re.compile(r"[\s\-_]+")


def normalize_code(raw: str) -> str:
    cleaned = _STRIP_RE.sub("", (raw or "").strip()).upper()
    if len(cleaned) == 22 and cleaned.startswith("EC") and cleaned[2:].isalnum():
        body = cleaned[2:]
        return f"EC-{body[0:5]}-{body[5:10]}-{body[10:15]}-{body[15:20]}"
    return (raw or "").strip().upper()


def generate_code() -> str:
    groups = ["".join(secrets.choice(CODE_ALPHABET) for _ in range(5)) for _ in range(4)]
    return "EC-" + "-".join(groups)


async def _generate_unique_codes(db: AsyncSession, count: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    while len(result) < count:
        needed = count - len(result)
        candidates: list[str] = []
        while len(candidates) < needed:
            c = generate_code()
            if c not in seen:
                seen.add(c)
                candidates.append(c)
        existing = set(
            (
                await db.scalars(
                    select(RedemptionCode.code).where(RedemptionCode.code.in_(candidates))
                )
            ).all()
        )
        for c in candidates:
            if c not in existing:
                result.append(c)
    return result


async def _local_today(db: AsyncSession) -> date:
    tz_name = await get_settings_store().get(
        db, "TIMEZONE", AUTOMATION_SPECS["TIMEZONE"].default_value()
    )
    return local_today(str(tz_name))


def _iso(dt: datetime | None) -> str | None:
    return to_iso_z(dt) if dt is not None else None


async def _validate_standard_plan(db: AsyncSession, plan_id: int) -> BillingPlan:
    plan = await db.get(BillingPlan, plan_id)
    if plan is None:
        raise ApiError(422, "validation.invalid", detail="所选套餐不存在")
    if plan.plan_type != "standard":
        raise ApiError(422, "validation.invalid", detail="兑换码仅支持绑定标准套餐，不支持试用套餐")
    return plan


def _effective_status(row: RedemptionCode, now: datetime) -> str:
    if row.status == "unused" and row.expires_at is not None and row.expires_at <= now:
        return "expired"
    return row.status


# --------------------------------------------------------------------------- #
# Batch / Export / Code Admin Operations
# --------------------------------------------------------------------------- #


async def _build_batch_outs(
    db: AsyncSession, batches: list[RedemptionBatch]
) -> list[RedemptionBatchOut]:
    if not batches:
        return []
    now = utc_naive_now()
    batch_ids = [b.id for b in batches]

    stats_stmt = (
        select(
            RedemptionCode.batch_id,
            func.count(RedemptionCode.id).label("total_cnt"),
            func.sum(
                case(
                    (
                        (RedemptionCode.status == "unused")
                        & or_(RedemptionCode.expires_at.is_(None), RedemptionCode.expires_at > now),
                        1,
                    ),
                    else_=0,
                )
            ).label("unused_cnt"),
            func.sum(case((RedemptionCode.status == "redeemed", 1), else_=0)).label("redeemed_cnt"),
            func.sum(case((RedemptionCode.status == "void", 1), else_=0)).label("void_cnt"),
            func.sum(
                case(
                    (
                        (RedemptionCode.status == "unused")
                        & RedemptionCode.expires_at.is_not(None)
                        & (RedemptionCode.expires_at <= now),
                        1,
                    ),
                    else_=0,
                )
            ).label("expired_cnt"),
            func.sum(case((RedemptionCode.export_id.is_not(None), 1), else_=0)).label("exported_cnt"),
            func.sum(
                case(
                    (
                        (RedemptionCode.status == "unused")
                        & RedemptionCode.export_id.is_(None)
                        & or_(RedemptionCode.expires_at.is_(None), RedemptionCode.expires_at > now),
                        1,
                    ),
                    else_=0,
                )
            ).label("exportable_cnt"),
        )
        .where(RedemptionCode.batch_id.in_(batch_ids))
        .group_by(RedemptionCode.batch_id)
    )
    stats_map: dict[int, Any] = {}
    for r in (await db.execute(stats_stmt)).all():
        stats_map[int(r.batch_id)] = r

    plan_ids = {b.plan_id for b in batches if b.plan_id is not None}
    plan_map: dict[int, BillingPlan] = {}
    if plan_ids:
        for p in (await db.scalars(select(BillingPlan).where(BillingPlan.id.in_(plan_ids)))).all():
            plan_map[p.id] = p

    user_ids = {b.created_by for b in batches if b.created_by is not None}
    user_map: dict[int, str] = {}
    if user_ids:
        for u in (await db.scalars(select(PteroUser).where(PteroUser.id.in_(user_ids)))).all():
            user_map[int(u.id)] = u.username

    items: list[RedemptionBatchOut] = []
    for b in batches:
        st = stats_map.get(b.id)
        plan = plan_map.get(b.plan_id) if b.plan_id is not None else None
        total_cnt = int(st.total_cnt or 0) if st else b.quantity
        items.append(
            RedemptionBatchOut(
                id=b.id,
                name=b.name,
                source=b.source,
                spec_key=b.spec_key,
                plan_id=b.plan_id,
                plan_name=plan.display_name if plan else None,
                plan_code=plan.code if plan else None,
                days=b.days,
                amount_fen=b.amount_fen,
                channel=b.channel,
                quantity=total_cnt,
                unused_count=int(st.unused_cnt or 0) if st else 0,
                redeemed_count=int(st.redeemed_cnt or 0) if st else 0,
                void_count=int(st.void_cnt or 0) if st else 0,
                expired_count=int(st.expired_cnt or 0) if st else 0,
                exported_count=int(st.exported_cnt or 0) if st else 0,
                exportable_count=int(st.exportable_cnt or 0) if st else 0,
                expires_at=_iso(b.expires_at),
                created_by=b.created_by,
                created_by_username=user_map.get(b.created_by) if b.created_by is not None else None,
                created_at=to_iso_z(b.created_at),
            )
        )
    return items


async def create_batch(
    db: AsyncSession,
    *,
    payload: RedemptionBatchCreateRequest,
    actor: PteroUser,
) -> RedemptionBatchOut:
    plan = await _validate_standard_plan(db, payload.plan_id)
    now = utc_naive_now()
    if payload.expires_at is not None and payload.expires_at <= now:
        raise ApiError(422, "validation.invalid", detail="过期时间必须晚于当前时间")

    codes = await _generate_unique_codes(db, payload.quantity)
    batch = RedemptionBatch(
        name=payload.name,
        source="manual",
        spec_key=None,
        plan_id=plan.id,
        days=payload.days,
        amount_fen=payload.amount_fen,
        channel=payload.channel,
        quantity=payload.quantity,
        expires_at=payload.expires_at,
        created_by=int(actor.id),
        created_at=now,
    )
    db.add(batch)
    await db.flush()

    db.add_all(
        [
            RedemptionCode(
                code=c,
                batch_id=batch.id,
                plan_id=plan.id,
                days=payload.days,
                amount_fen=payload.amount_fen,
                channel=payload.channel,
                expires_at=payload.expires_at,
                status="unused",
                created_at=now,
            )
            for c in codes
        ]
    )
    await db.commit()

    await log_manager_activity(
        db,
        actor=actor.username,
        category="billing",
        operation=OperationResult(
            action="billing.redemption.batch_create",
            phase="execution",
            outcome="success",
            target={"batch_id": batch.id},
        ),
        detail_key="billing.redemption.batch_created",
        detail_params={
            "batch_id": batch.id,
            "name": batch.name,
            "quantity": batch.quantity,
            "plan_name": plan.display_name,
            "days": batch.days,
        },
    )
    outs = await _build_batch_outs(db, [batch])
    return outs[0]


async def list_batches(
    db: AsyncSession,
    *,
    source: str | None = None,
    plan_id: int | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> RedemptionBatchListResponse:
    stmt = select(RedemptionBatch)
    count_stmt = select(func.count(RedemptionBatch.id))
    filters = []
    if source:
        filters.append(RedemptionBatch.source == source)
    if plan_id is not None:
        filters.append(RedemptionBatch.plan_id == plan_id)
    if q and q.strip():
        kw = q.strip()
        like = f"%{kw}%"
        norm = normalize_code(kw)
        code_batch_subq = select(RedemptionCode.batch_id).where(
            or_(
                RedemptionCode.code.ilike(like),
                RedemptionCode.code == norm,
                RedemptionCode.external_order_id.ilike(like),
            )
        )
        filters.append(
            or_(
                RedemptionBatch.name.ilike(like),
                RedemptionBatch.id.in_(code_batch_subq),
            )
        )
    for f in filters:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    stmt = stmt.order_by(RedemptionBatch.id.desc()).limit(limit).offset(offset)
    rows = list((await db.scalars(stmt)).all())
    total = int(await db.scalar(count_stmt) or 0)
    items = await _build_batch_outs(db, rows)
    return RedemptionBatchListResponse(items=items, total=total)


async def get_batch_detail(db: AsyncSession, batch_id: int) -> RedemptionBatchDetailOut:
    batch = await db.get(RedemptionBatch, batch_id)
    if batch is None:
        raise ApiError(404, "resource.not_found", detail="兑换码批次不存在")
    base = (await _build_batch_outs(db, [batch]))[0]
    exports = list(
        (
            await db.scalars(
                select(RedemptionExport)
                .where(RedemptionExport.batch_id == batch_id)
                .order_by(RedemptionExport.id.desc())
            )
        ).all()
    )
    user_ids = {e.created_by for e in exports if e.created_by is not None}
    user_map: dict[int, str] = {}
    if user_ids:
        for u in (await db.scalars(select(PteroUser).where(PteroUser.id.in_(user_ids)))).all():
            user_map[int(u.id)] = u.username

    export_outs = [
        RedemptionExportOut(
            id=e.id,
            batch_id=e.batch_id,
            quantity=e.quantity,
            created_by=e.created_by,
            created_by_username=user_map.get(e.created_by) if e.created_by is not None else None,
            created_at=to_iso_z(e.created_at),
        )
        for e in exports
    ]
    return RedemptionBatchDetailOut(**base.model_dump(), exports=export_outs)


async def create_export(
    db: AsyncSession,
    *,
    batch_id: int,
    quantity: int | None,
    actor: PteroUser,
) -> tuple[RedemptionExport, str]:
    batch = await db.get(RedemptionBatch, batch_id)
    if batch is None:
        raise ApiError(404, "resource.not_found", detail="兑换码批次不存在")

    now = utc_naive_now()
    stmt = (
        select(RedemptionCode)
        .where(
            RedemptionCode.batch_id == batch_id,
            RedemptionCode.status == "unused",
            RedemptionCode.export_id.is_(None),
            or_(RedemptionCode.expires_at.is_(None), RedemptionCode.expires_at > now),
        )
        .order_by(RedemptionCode.id.asc())
        .with_for_update()
    )
    if quantity is not None:
        stmt = stmt.limit(quantity)

    rows = list((await db.scalars(stmt)).all())
    if not rows:
        await db.rollback()
        raise ApiError(409, "resource.conflict", detail="当前批次没有可导出的未导出有效兑换码")
    if quantity is not None and len(rows) < quantity:
        await db.rollback()
        raise ApiError(
            409,
            "resource.conflict",
            detail=f"可导出数量不足（剩余 {len(rows)} 张，请求 {quantity} 张）",
        )

    export_row = RedemptionExport(
        batch_id=batch_id,
        quantity=len(rows),
        created_by=int(actor.id),
        created_at=now,
    )
    db.add(export_row)
    await db.flush()

    for r in rows:
        r.export_id = export_row.id
    txt = "\r\n".join(r.code for r in rows) + "\r\n"
    await db.commit()

    await log_manager_activity(
        db,
        actor=actor.username,
        category="billing",
        operation=OperationResult(
            action="billing.redemption.export",
            phase="execution",
            outcome="success",
            target={"batch_id": batch_id},
        ),
        detail_key="billing.redemption.exported",
        detail_params={
            "batch_id": batch_id,
            "export_id": export_row.id,
            "quantity": export_row.quantity,
        },
    )
    return export_row, txt


async def get_export_txt(db: AsyncSession, *, export_id: int) -> tuple[RedemptionExport, str]:
    export_row = await db.get(RedemptionExport, export_id)
    if export_row is None:
        raise ApiError(404, "resource.not_found", detail="导出记录不存在")
    codes = list(
        (
            await db.scalars(
                select(RedemptionCode.code)
                .where(RedemptionCode.export_id == export_id)
                .order_by(RedemptionCode.id.asc())
            )
        ).all()
    )
    txt = ("\r\n".join(codes) + "\r\n") if codes else ""
    return export_row, txt


async def _serialize_codes(
    db: AsyncSession, rows: list[RedemptionCode]
) -> list[RedemptionCodeOut]:
    if not rows:
        return []
    now = utc_naive_now()

    batch_ids = {r.batch_id for r in rows}
    batch_map: dict[int, RedemptionBatch] = {}
    if batch_ids:
        for b in (await db.scalars(select(RedemptionBatch).where(RedemptionBatch.id.in_(batch_ids)))).all():
            batch_map[b.id] = b

    plan_ids = {r.plan_id for r in rows if r.plan_id is not None}
    plan_map: dict[int, str] = {}
    if plan_ids:
        for p in (await db.scalars(select(BillingPlan).where(BillingPlan.id.in_(plan_ids)))).all():
            plan_map[p.id] = p.display_name

    user_ids = {r.redeemed_by for r in rows if r.redeemed_by is not None}
    user_map: dict[int, str] = {}
    if user_ids:
        for u in (await db.scalars(select(PteroUser).where(PteroUser.id.in_(user_ids)))).all():
            user_map[int(u.id)] = u.username

    order_ids = {r.order_id for r in rows if r.order_id is not None}
    order_map: dict[int, str] = {}
    if order_ids:
        for o in (await db.scalars(select(BillingOrder).where(BillingOrder.id.in_(order_ids)))).all():
            order_map[o.id] = o.order_no

    server_ids = {r.target_server_id for r in rows if r.target_server_id is not None}
    server_map: dict[int, str] = {}
    if server_ids:
        for srv in (await db.scalars(select(PteroServer).where(PteroServer.id.in_(server_ids)))).all():
            server_map[int(srv.id)] = srv.name

    out: list[RedemptionCodeOut] = []
    for r in rows:
        batch_obj = batch_map.get(r.batch_id)
        out.append(
            RedemptionCodeOut(
                id=r.id,
                code=r.code,
                batch_id=r.batch_id,
                batch_name=batch_obj.name if batch_obj else None,
                source=batch_obj.source if batch_obj else "manual",
                plan_id=r.plan_id,
                plan_name=plan_map.get(r.plan_id) if r.plan_id is not None else None,
                days=r.days,
                amount_fen=r.amount_fen,
                channel=r.channel,
                status=_effective_status(r, now),
                export_id=r.export_id,
                external_order_id=r.external_order_id,
                redeemed_by=r.redeemed_by,
                redeemed_by_username=user_map.get(r.redeemed_by) if r.redeemed_by is not None else None,
                redeemed_at=_iso(r.redeemed_at),
                order_id=r.order_id,
                order_no=order_map.get(r.order_id) if r.order_id is not None else None,
                target_server_id=r.target_server_id,
                target_server_name=server_map.get(r.target_server_id) if r.target_server_id is not None else None,
                expires_at=_iso(r.expires_at),
                voided_at=_iso(r.voided_at),
                void_reason=r.void_reason,
                created_at=to_iso_z(r.created_at),
            )
        )
    return out


async def list_codes(
    db: AsyncSession,
    *,
    batch_id: int | None = None,
    status_filter: str | None = None,
    export_id: int | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> RedemptionCodeListResponse:
    now = utc_naive_now()
    stmt = select(RedemptionCode)
    count_stmt = select(func.count(RedemptionCode.id))
    filters = []

    if batch_id is not None:
        filters.append(RedemptionCode.batch_id == batch_id)
    if export_id is not None:
        filters.append(RedemptionCode.export_id == export_id)
    if status_filter:
        if status_filter == "expired":
            filters.append(RedemptionCode.status == "unused")
            filters.append(RedemptionCode.expires_at.is_not(None))
            filters.append(RedemptionCode.expires_at <= now)
        elif status_filter == "unused":
            filters.append(RedemptionCode.status == "unused")
            filters.append(
                or_(RedemptionCode.expires_at.is_(None), RedemptionCode.expires_at > now)
            )
        else:
            filters.append(RedemptionCode.status == status_filter)

    if q and q.strip():
        kw = q.strip()
        like = f"%{kw}%"
        norm = normalize_code(kw)
        user_subq = select(PteroUser.id).where(PteroUser.username.ilike(like))
        order_subq = select(BillingOrder.id).where(BillingOrder.order_no.ilike(like))
        filters.append(
            or_(
                RedemptionCode.code.ilike(like),
                RedemptionCode.code == norm,
                RedemptionCode.external_order_id.ilike(like),
                cast(RedemptionCode.redeemed_by, String).ilike(like),
                RedemptionCode.redeemed_by.in_(user_subq),
                RedemptionCode.order_id.in_(order_subq),
            )
        )

    for f in filters:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    stmt = stmt.order_by(RedemptionCode.id.desc()).limit(limit).offset(offset)
    rows = list((await db.scalars(stmt)).all())
    total = int(await db.scalar(count_stmt) or 0)
    items = await _serialize_codes(db, rows)
    return RedemptionCodeListResponse(items=items, total=total)


async def void_code(
    db: AsyncSession,
    *,
    code_id: int,
    reason: str | None,
    actor: PteroUser,
) -> RedemptionCodeOut:
    row = await db.scalar(
        select(RedemptionCode).where(RedemptionCode.id == code_id).with_for_update()
    )
    if row is None:
        raise ApiError(404, "resource.not_found", detail="兑换码不存在")
    if row.status == "redeemed":
        await db.rollback()
        raise ApiError(409, "redemption.already_redeemed")
    if row.status == "redeeming":
        await db.rollback()
        raise ApiError(409, "redemption.in_progress")
    if row.status == "void":
        out = (await _serialize_codes(db, [row]))[0]
        await db.rollback()
        return out

    row.status = "void"
    row.voided_by = int(actor.id)
    row.voided_at = utc_naive_now()
    row.void_reason = (reason or "").strip() or None
    await db.commit()

    await log_manager_activity(
        db,
        actor=actor.username,
        category="billing",
        operation=OperationResult(
            action="billing.redemption.void",
            phase="execution",
            outcome="success",
            target={"code_id": row.id},
        ),
        detail_key="billing.redemption.code_voided",
        detail_params={
            "code": row.code,
            "batch_id": row.batch_id,
            "reason": row.void_reason or "",
        },
    )
    return (await _serialize_codes(db, [row]))[0]


async def void_batch(
    db: AsyncSession,
    *,
    batch_id: int,
    reason: str | None,
    actor: PteroUser,
) -> RedemptionBatchVoidOut:
    batch = await db.get(RedemptionBatch, batch_id)
    if batch is None:
        raise ApiError(404, "resource.not_found", detail="兑换码批次不存在")

    now = utc_naive_now()
    clean_reason = (reason or "").strip() or None
    res = await db.execute(
        update(RedemptionCode)
        .where(
            RedemptionCode.batch_id == batch_id,
            RedemptionCode.status == "unused",
        )
        .values(
            status="void",
            voided_by=int(actor.id),
            voided_at=now,
            void_reason=clean_reason,
        )
    )
    voided_count = int(res.rowcount or 0)
    await db.commit()

    await log_manager_activity(
        db,
        actor=actor.username,
        category="billing",
        operation=OperationResult(
            action="billing.redemption.batch_void",
            phase="execution",
            outcome="success",
            target={"batch_id": batch_id},
        ),
        detail_key="billing.redemption.batch_voided",
        detail_params={
            "batch_id": batch_id,
            "name": batch.name,
            "voided_count": voided_count,
            "reason": clean_reason or "",
        },
    )
    return RedemptionBatchVoidOut(batch_id=batch_id, voided_count=voided_count)


# --------------------------------------------------------------------------- #
# Agiso 91 Custom Pull API
# --------------------------------------------------------------------------- #


async def verify_api_token(db: AsyncSession, provided_token: str | None) -> None:
    store = get_settings_store()
    enabled = bool(
        await store.get(
            db,
            "REDEMPTION_API_ENABLED",
            BILLING_SPECS["REDEMPTION_API_ENABLED"].default_value(),
        )
    )
    if not enabled:
        raise ApiError(403, "redemption.api_disabled")

    token = str(
        await store.get(
            db,
            "REDEMPTION_API_TOKEN",
            BILLING_SPECS["REDEMPTION_API_TOKEN"].default_value(),
        )
        or ""
    ).strip()
    if not token or not provided_token:
        raise ApiError(401, "auth.invalid_token")
    if not secrets.compare_digest(token, provided_token.strip()):
        raise ApiError(401, "auth.invalid_token")


async def issue_via_agiso_api(
    db: AsyncSession, payload: AgisoIssueRequest
) -> AgisoIssueData:
    plan = await db.scalar(
        select(BillingPlan).where(BillingPlan.code == payload.plan_code)
    )
    if plan is None or not plan.is_active or plan.plan_type != "standard":
        await db.rollback()
        raise ApiError(404, "redemption.spec_not_found")

    selected = next(
        (
            opt
            for opt in (plan.period_options or [])
            if int(opt.get("count", 0)) == payload.period_count
        ),
        None,
    )
    if selected is None:
        await db.rollback()
        raise ApiError(404, "redemption.spec_not_found")

    store = get_settings_store()
    default_channel = str(
        await store.get(
            db,
            "REDEMPTION_API_DEFAULT_CHANNEL",
            BILLING_SPECS["REDEMPTION_API_DEFAULT_CHANNEL"].default_value(),
        )
        or "taobao"
    )
    if default_channel not in ("taobao", "xianyu", "other"):
        default_channel = "taobao"

    valid_days = int(
        await store.get(
            db,
            "REDEMPTION_API_VALID_DAYS",
            BILLING_SPECS["REDEMPTION_API_VALID_DAYS"].default_value(),
        )
        or 0
    )

    channel = payload.channel or default_channel
    req_order_id = payload.order_id
    plan_code_str = plan.code
    plan_id_val = plan.id
    plan_display_name = plan.display_name
    days = int(plan.days) * payload.period_count
    discount_pct = Decimal(str(selected.get("discount_pct", 0)))
    spec_price_fen = int(
        (
            Decimal(str(plan.price_fen * payload.period_count))
            * (Decimal("100") - discount_pct)
            / Decimal("100")
        ).quantize(Decimal("1"))
    )

    now = utc_naive_now()
    spec_key = f"{plan_id_val}:{payload.period_count}"
    batch_name = f"[自动发卡] {plan_display_name} ({payload.period_count}周期/{days}天)"

    batch = await db.scalar(
        select(RedemptionBatch)
        .where(RedemptionBatch.spec_key == spec_key)
        .with_for_update()
    )
    if batch is None:
        try:
            async with db.begin_nested():
                batch = RedemptionBatch(
                    name=batch_name,
                    source="api",
                    spec_key=spec_key,
                    plan_id=plan_id_val,
                    days=days,
                    amount_fen=spec_price_fen,
                    channel=channel,
                    quantity=0,
                    expires_at=None,
                    created_by=None,
                    created_at=now,
                )
                db.add(batch)
                await db.flush()
        except IntegrityError:
            batch = await db.scalar(
                select(RedemptionBatch)
                .where(RedemptionBatch.spec_key == spec_key)
                .with_for_update()
            )
            if batch is None:
                await db.rollback()
                raise ApiError(409, "resource.conflict")

    prior_order_count = 0
    if req_order_id:
        all_order_rows = list(
            (
                await db.scalars(
                    select(RedemptionCode)
                    .where(
                        RedemptionCode.channel == channel,
                        RedemptionCode.external_request_id == req_order_id,
                    )
                    .order_by(RedemptionCode.id.asc())
                    .with_for_update()
                )
            ).all()
        )
        same_spec_rows = [r for r in all_order_rows if r.batch_id == batch.id]
        if same_spec_rows:
            if len(same_spec_rows) != payload.num:
                await db.rollback()
                raise ApiError(
                    409,
                    "resource.conflict",
                    detail=(
                        f"订单号 {req_order_id} 已发放过 {len(same_spec_rows)} 张同规格兑换码，"
                        f"与本次请求数量 {payload.num} 不一致"
                    ),
                )
            cards = [AgisoCardItem(cardNo=r.code) for r in same_spec_rows]
            replay_data = AgisoIssueData(
                cardNo=cards[0].cardNo,
                cards=cards,
                planCode=plan_code_str,
                periodCount=payload.period_count,
                orderId=req_order_id,
                quantity=len(cards),
                days=same_spec_rows[0].days,
                expiresAt=_iso(same_spec_rows[0].expires_at),
            )
            await db.rollback()
            return replay_data
        prior_order_count = len(all_order_rows)

    expires_at = now + timedelta(days=valid_days) if valid_days > 0 else None
    if payload.amount_yuan is not None and payload.amount_yuan > 0:
        unit_amount_fen = max(1, int(round((payload.amount_yuan * 100) / payload.num)))
    else:
        unit_amount_fen = spec_price_fen

    codes = await _generate_unique_codes(db, payload.num)
    new_rows: list[RedemptionCode] = []
    for idx, c in enumerate(codes):
        ext_ord: str | None = None
        if req_order_id:
            seq = prior_order_count + idx + 1
            if seq == 1:
                ext_ord = req_order_id
            else:
                suffix = f"#{seq}"
                ext_ord = f"{req_order_id[: max(1, 64 - len(suffix))]}{suffix}"
        new_rows.append(
            RedemptionCode(
                code=c,
                batch_id=batch.id,
                plan_id=plan_id_val,
                days=days,
                amount_fen=unit_amount_fen,
                channel=channel,
                expires_at=expires_at,
                external_request_id=req_order_id,
                external_order_id=ext_ord,
                status="unused",
                created_at=now,
            )
        )
    db.add_all(new_rows)
    batch.name = batch_name
    batch.days = days
    batch.amount_fen = spec_price_fen
    batch.channel = channel
    batch.quantity = (batch.quantity or 0) + payload.num
    batch_id_val = batch.id
    await db.commit()

    await log_manager_activity(
        db,
        actor="agiso",
        category="billing",
        operation=OperationResult(
            action="billing.redemption.api_issue",
            phase="execution",
            outcome="success",
            target={"plan_id": plan_id_val, "batch_id": batch_id_val},
        ),
        detail_key="billing.redemption.api_issued",
        detail_params={
            "plan_code": plan_code_str,
            "period_count": payload.period_count,
            "quantity": payload.num,
            "external_order_id": req_order_id or "-",
        },
    )

    cards = [AgisoCardItem(cardNo=c) for c in codes]
    return AgisoIssueData(
        cardNo=cards[0].cardNo,
        cards=cards,
        planCode=plan_code_str,
        periodCount=payload.period_count,
        orderId=req_order_id,
        quantity=len(cards),
        days=days,
        expiresAt=_iso(expires_at),
    )


# --------------------------------------------------------------------------- #
# User Preview & Redemption
# --------------------------------------------------------------------------- #


async def _find_compatible_servers(
    db: AsyncSession,
    *,
    user_id: int,
    target_plan_id: int,
    days: int,
    today: date,
) -> list[RedeemCompatibleServerOut]:
    rows = list(
        (
            await db.scalars(
                select(PteroServer)
                .where(PteroServer.owner_id == user_id)
                .order_by(PteroServer.id.desc())
            )
        ).all()
    )
    if not rows:
        return []

    visible_servers = [
        s for s in rows if not (s.external_id and s.external_id.startswith("pending:"))
    ]
    if not visible_servers:
        return []

    sids = [int(s.id) for s in visible_servers]
    metas = {
        int(m.server_id): m
        for m in (
            await db.scalars(select(ServerMeta).where(ServerMeta.server_id.in_(sids)))
        ).all()
    }
    bound_plan_ids = {m.plan_id for m in metas.values() if m.plan_id is not None}
    bound_plans: dict[int, BillingPlan] = {}
    if bound_plan_ids:
        for p in (
            await db.scalars(
                select(BillingPlan).where(BillingPlan.id.in_(bound_plan_ids))
            )
        ).all():
            bound_plans[p.id] = p

    compatible: list[RedeemCompatibleServerOut] = []
    for srv in visible_servers:
        meta = metas.get(int(srv.id))
        if meta is None or meta.plan_id is None:
            continue
        kind: Literal["renew", "convert"] | None = None
        if meta.is_trial:
            trial_plan = bound_plans.get(meta.plan_id)
            if trial_plan is not None and trial_plan.linked_plan_id == target_plan_id:
                kind = "convert"
        else:
            if meta.plan_id == target_plan_id:
                kind = "renew"
        if kind is None:
            continue

        prev = meta.expiration_date
        base = prev if (prev is not None and prev > today) else today
        projected = base + timedelta(days=days)
        compatible.append(
            RedeemCompatibleServerOut(
                id=int(srv.id),
                name=srv.name,
                kind=kind,
                is_trial=bool(meta.is_trial),
                is_suspended=bool(srv.is_suspended),
                current_expiration_date=prev.isoformat() if prev else None,
                projected_expiration_date=projected.isoformat(),
            )
        )
    return compatible


def _plan_summary(plan: BillingPlan) -> RedeemPlanSummaryOut:
    return RedeemPlanSummaryOut(
        id=plan.id,
        code=plan.code,
        display_name=plan.display_name,
        cpu=plan.cpu,
        memory_mb=plan.memory_mb,
        disk_mb=plan.disk_mb,
        llm_enabled=plan.llm_enabled,
        llm_quota_grant=plan.llm_quota_grant,
    )


async def preview_code(
    db: AsyncSession, *, user: PteroUser, raw_code: str
) -> RedeemPreviewResponse:
    norm = normalize_code(raw_code)
    row = await db.scalar(select(RedemptionCode).where(RedemptionCode.code == norm))
    if row is None:
        raise ApiError(404, "redemption.not_found")

    now = utc_naive_now()
    if row.status == "void":
        raise ApiError(409, "redemption.voided")
    if row.status == "redeeming":
        raise ApiError(409, "redemption.in_progress")

    plan = await db.get(BillingPlan, row.plan_id) if row.plan_id is not None else None

    if row.status == "redeemed":
        if row.redeemed_by == int(user.id) and row.order_id is not None and plan is not None:
            order = await db.get(BillingOrder, row.order_id)
            today = await _local_today(db)
            return RedeemPreviewResponse(
                code=row.code,
                days=row.days,
                expires_at=_iso(row.expires_at),
                plan=_plan_summary(plan),
                new_server_expiration_date=(today + timedelta(days=row.days)).isoformat(),
                compatible_servers=[],
                already_redeemed_by_me=True,
                order_id=row.order_id,
                order_no=order.order_no if order else None,
                target_server_id=row.target_server_id,
            )
        raise ApiError(409, "redemption.already_redeemed")

    if row.expires_at is not None and row.expires_at <= now:
        raise ApiError(409, "redemption.expired")
    if plan is None or plan.plan_type != "standard":
        raise ApiError(409, "redemption.plan_unavailable")

    today = await _local_today(db)
    compatible = await _find_compatible_servers(
        db,
        user_id=int(user.id),
        target_plan_id=plan.id,
        days=row.days,
        today=today,
    )
    return RedeemPreviewResponse(
        code=row.code,
        days=row.days,
        expires_at=_iso(row.expires_at),
        plan=_plan_summary(plan),
        new_server_expiration_date=(today + timedelta(days=row.days)).isoformat(),
        compatible_servers=compatible,
        already_redeemed_by_me=False,
    )


async def redeem_code(
    db: AsyncSession,
    *,
    user: PteroUser,
    raw_code: str,
    target_server_id: int | None,
) -> RedeemExecuteResponse:
    norm = normalize_code(raw_code)
    user_id = int(user.id)
    now = utc_naive_now()

    # Phase 1: Lock & validate code, then transition to 'redeeming' before any
    # external Wings calls (since server_lifecycle.create_server commits internally).
    row = await db.scalar(
        select(RedemptionCode).where(RedemptionCode.code == norm).with_for_update()
    )
    if row is None:
        raise ApiError(404, "redemption.not_found")
    if row.status == "void":
        await db.rollback()
        raise ApiError(409, "redemption.voided")
    if row.status == "redeeming":
        await db.rollback()
        raise ApiError(409, "redemption.in_progress")
    if row.status == "redeemed":
        if row.redeemed_by == user_id and row.order_id is not None:
            order = await db.get(BillingOrder, row.order_id)
            effect = await db.get(BillingOrderEffect, row.order_id)
            srv = await db.get(PteroServer, row.target_server_id) if row.target_server_id else None
            if order is not None and effect is not None:
                kind_lit: Literal["new_purchase", "renew", "convert"] = (
                    "convert"
                    if order.kind == "convert"
                    else ("renew" if order.kind == "renew" else "new_purchase")
                )
                replay_resp = RedeemExecuteResponse(
                    code=row.code,
                    kind=kind_lit,
                    order_id=order.id,
                    order_no=order.order_no,
                    server_id=effect.server_id,
                    server_name=srv.name if srv else f"#{effect.server_id}",
                    days=effect.days,
                    new_expiration_date=effect.new_expiration_date.isoformat(),
                )
                await db.rollback()
                return replay_resp
        await db.rollback()
        raise ApiError(409, "redemption.already_redeemed")

    if row.expires_at is not None and row.expires_at <= now:
        await db.rollback()
        raise ApiError(409, "redemption.expired")

    plan = await db.get(BillingPlan, row.plan_id) if row.plan_id is not None else None
    if plan is None or plan.plan_type != "standard":
        await db.rollback()
        raise ApiError(409, "redemption.plan_unavailable")

    kind: Literal["new_purchase", "renew", "convert"] = "new_purchase"
    was_suspended = False
    target_server_name = ""

    if target_server_id is not None:
        srv = await db.get(PteroServer, target_server_id)
        if srv is None or srv.owner_id != user_id or (
            srv.external_id and srv.external_id.startswith("pending:")
        ):
            await db.rollback()
            raise ApiError(422, "redemption.server_incompatible")
        meta = await db.get(ServerMeta, target_server_id)
        if meta is None or meta.plan_id is None:
            await db.rollback()
            raise ApiError(422, "redemption.server_incompatible")
        if meta.is_trial:
            trial_plan = await db.get(BillingPlan, meta.plan_id)
            if trial_plan is None or trial_plan.linked_plan_id != plan.id:
                await db.rollback()
                raise ApiError(422, "redemption.server_incompatible")
            kind = "convert"
        else:
            if meta.plan_id != plan.id:
                await db.rollback()
                raise ApiError(422, "redemption.server_incompatible")
            kind = "renew"
        was_suspended = bool(srv.is_suspended)
        target_server_name = srv.name

    code_id = row.id
    code_str = row.code
    code_days = row.days
    code_amount_fen = row.amount_fen
    code_channel = row.channel
    code_ext_order_id = row.external_order_id
    plan_id = plan.id

    row.status = "redeeming"
    row.redeemed_by = user_id
    await db.commit()

    # Phase 2: Provision or sync build, then atomically commit BillingOrder + RedemptionCode.
    created_server_id: int | None = None
    converted_build_prev: tuple[int, dict[str, Any]] | None = None
    try:
        plan_fresh = await db.get(BillingPlan, plan_id)
        if plan_fresh is None:
            raise ApiError(409, "redemption.plan_unavailable")

        today = await _local_today(db)
        order_no = gen_order_no()
        snapshot = _build_snapshot(
            plan_fresh,
            {"count": 1, "discount_pct": 0},
            code_amount_fen,
            code_days,
        )
        snapshot["redemption_code"] = code_str

        if kind == "new_purchase":
            alloc_count = max(1, plan_fresh.allocation_limit)
            allocs = list(
                (
                    await db.scalars(
                        select(Allocation.id)
                        .where(
                            Allocation.node_id == plan_fresh.node_id,
                            Allocation.server_id.is_(None),
                        )
                        .order_by(Allocation.id.asc())
                        .limit(alloc_count)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            if len(allocs) < alloc_count:
                raise ApiError(
                    409,
                    "resource.conflict",
                    detail=f"节点可用端口不足，当前套餐需要 {alloc_count} 个端口",
                )
            primary_alloc, *extra_allocs = allocs
            prev_exp: date | None = None
            new_exp = today + timedelta(days=code_days)
            server_name = f"{user.username}-{order_no[-6:]}"
            created = await server_lifecycle.create_server(
                db,
                owner_id=user_id,
                node_id=plan_fresh.node_id,
                allocation_id=primary_alloc,
                allocation_additional=extra_allocs or None,
                egg_id=plan_fresh.egg_id,
                name=server_name,
                description=f"到期时间：{new_exp.strftime('%Y/%m/%d')}",
                memory=plan_fresh.memory_mb,
                swap=plan_fresh.swap_mb,
                disk=plan_fresh.disk_mb,
                io=plan_fresh.io,
                cpu=plan_fresh.cpu,
                image=plan_fresh.docker_image,
                startup=plan_fresh.startup_command,
                environment={k: str(v) for k, v in (plan_fresh.env_defaults or {}).items()},
                database_limit=plan_fresh.database_limit,
                backup_limit=plan_fresh.backup_limit,
                allocation_limit=plan_fresh.allocation_limit,
                oom_disabled=plan_fresh.oom_disabled,
            )
            created_server_id = int(created.id)
            server_id = created_server_id
            target_server_name = created.name
        else:
            assert target_server_id is not None
            server_id = target_server_id
            if kind == "convert":
                srv_before = await db.get(PteroServer, server_id, populate_existing=True)
                if srv_before is None:
                    raise ApiError(422, "redemption.server_incompatible")
                prev_build: dict[str, Any] = {
                    "cpu": int(srv_before.cpu),
                    "memory": int(srv_before.memory),
                    "disk": int(srv_before.disk),
                    "swap": int(srv_before.swap),
                    "io": int(srv_before.io),
                    "database_limit": int(srv_before.database_limit or 0),
                    "backup_limit": int(srv_before.backup_limit),
                    "allocation_limit": srv_before.allocation_limit,
                    "oom_disabled": bool(srv_before.oom_disabled),
                }
                await server_lifecycle.update_server_build(
                    db,
                    server_id,
                    cpu=plan_fresh.cpu,
                    memory=plan_fresh.memory_mb,
                    disk=plan_fresh.disk_mb,
                    swap=plan_fresh.swap_mb,
                    io=plan_fresh.io,
                    database_limit=plan_fresh.database_limit,
                    backup_limit=plan_fresh.backup_limit,
                    allocation_limit=plan_fresh.allocation_limit,
                    oom_disabled=plan_fresh.oom_disabled,
                )
                converted_build_prev = (server_id, prev_build)

            meta_locked = await db.scalar(
                select(ServerMeta)
                .where(ServerMeta.server_id == server_id)
                .with_for_update()
            )
            if meta_locked is None:
                raise ApiError(422, "redemption.server_incompatible")
            prev_exp = meta_locked.expiration_date
            base_date = prev_exp if (prev_exp is not None and prev_exp > today) else today
            new_exp = base_date + timedelta(days=code_days)
            meta_locked.expiration_date = new_exp
            if kind == "convert":
                meta_locked.plan_id = plan_fresh.id
                meta_locked.is_trial = False

        # Guard against external_order_id collision if an admin manually entered the same external order id earlier.
        final_ext_id = code_ext_order_id
        note = f"兑换码 {code_str}"
        if final_ext_id:
            dup_order = await db.scalar(
                select(BillingOrder.id)
                .where(
                    BillingOrder.channel == code_channel,
                    BillingOrder.external_order_id == final_ext_id,
                )
                .limit(1)
            )
            if dup_order is not None:
                suffix = f"#R{code_id}"
                final_ext_id = f"{final_ext_id[: max(1, 64 - len(suffix))]}{suffix}"
                note = f"兑换码 {code_str}（原单号 {code_ext_order_id}）"

        commit_now = utc_naive_now()
        order = BillingOrder(
            order_no=order_no,
            user_id=user_id,
            plan_id=plan_fresh.id,
            plan_snapshot=snapshot,
            kind=kind,
            channel=code_channel,
            external_order_id=final_ext_id,
            operator="redemption",
            channel_note=note,
            period_count=1,
            discount_pct=Decimal("0"),
            total_fen=code_amount_fen,
            total_days=code_days,
            target_server_id=server_id,
            status="applied",
            received_fen=code_amount_fen,
            applied_at=commit_now,
        )
        db.add(order)
        await db.flush()

        effect = BillingOrderEffect(
            order_id=order.id,
            server_id=server_id,
            effect_type=kind,
            days=code_days,
            prev_expiration_date=prev_exp,
            new_expiration_date=new_exp,
            effect_committed_at=commit_now,
            post_actions_done_at=commit_now if kind == "new_purchase" else None,
        )
        db.add(effect)

        if kind == "new_purchase":
            await _upsert_meta_expiration_plan_trial(
                db, server_id, new_exp, plan_fresh.id, False
            )
            await db.execute(
                update(PteroServer)
                .where(PteroServer.id == server_id)
                .values(external_id=f"order:{order.id}", updated_at=commit_now)
            )

        code_locked = await db.scalar(
            select(RedemptionCode).where(RedemptionCode.id == code_id).with_for_update()
        )
        if code_locked is not None:
            code_locked.status = "redeemed"
            code_locked.redeemed_by = user_id
            code_locked.redeemed_at = commit_now
            code_locked.order_id = order.id
            code_locked.target_server_id = server_id

        order_id_val = int(order.id)
        order_no_val = str(order.order_no)
        actor_username = str(user.username)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        if created_server_id is not None:
            try:
                await server_lifecycle.delete_server(db, created_server_id)
            except Exception:
                logger.exception(
                    "Failed to clean up newly created server %s after redemption error",
                    created_server_id,
                )
                await db.rollback()
        if converted_build_prev is not None:
            conv_srv_id, conv_prev = converted_build_prev
            try:
                await server_lifecycle.update_server_build(db, conv_srv_id, **conv_prev)
            except Exception:
                logger.exception(
                    "Failed to revert converted server %s build after redemption error",
                    conv_srv_id,
                )
                await db.rollback()
        try:
            await db.execute(
                update(RedemptionCode)
                .where(
                    RedemptionCode.id == code_id,
                    RedemptionCode.status == "redeeming",
                )
                .values(status="unused", redeemed_by=None)
            )
            await db.commit()
        except Exception:
            logger.exception("Failed to release redeeming lock on code %s", code_id)
            await db.rollback()

        if isinstance(exc, ApiError):
            raise
        if isinstance(exc, LifecycleValidationError):
            raise ApiError(422, "validation.invalid", detail=str(exc)) from exc
        if isinstance(exc, LifecycleError):
            raise ApiError(502, "dependency.failed", detail=str(exc)) from exc
        logger.exception("Unexpected error redeeming code %s", code_str)
        raise ApiError(502, "billing.order.apply_failed", detail=str(exc)[:200]) from exc

    # Phase 3: Best-effort post-actions (never revert committed redemption).
    post_ok = True
    if kind != "new_purchase":
        try:
            await server_lifecycle.update_server_expiration_description(
                db, server_id, new_exp
            )
        except Exception:
            post_ok = False
            logger.warning(
                "Failed to update expiration description on server %s after redemption",
                server_id,
                exc_info=True,
            )
            await db.rollback()

        if was_suspended:
            try:
                await server_lifecycle.unsuspend_server(db, server_id)
            except Exception:
                post_ok = False
                logger.warning(
                    "Failed to unsuspend server %s after redemption",
                    server_id,
                    exc_info=True,
                )
                await db.rollback()

        if post_ok:
            try:
                await db.execute(
                    update(BillingOrderEffect)
                    .where(BillingOrderEffect.order_id == order_id_val)
                    .values(post_actions_done_at=utc_naive_now())
                )
                await db.commit()
            except Exception:
                await db.rollback()

    if kind != "renew":
        try:
            from app.services.llm_provision import provision as llm_provision

            if kind == "convert":
                await llm_provision.update_for_upgrade(db, server_id, snapshot)
            elif bool(snapshot.get("llm_enabled")) and int(
                snapshot.get("llm_quota_grant", 0)
            ) > 0:
                await llm_provision.provision_for_server(
                    db, server_id, user_id, snapshot
                )
            await db.commit()
        except Exception:
            logger.warning(
                "LLM provision failed after redemption order %s server %s (non-blocking)",
                order_id_val,
                server_id,
                exc_info=True,
            )
            await db.rollback()

    await log_manager_activity(
        db,
        actor=actor_username,
        category="billing",
        operation=OperationResult(
            action="billing.redemption.redeem",
            phase="execution",
            outcome="success",
            target={"order_id": order_id_val, "server_id": server_id},
        ),
        detail_key="billing.redemption.redeemed",
        detail_params={
            "code": code_str,
            "order_no": order_no_val,
            "order_kind": kind,
            "server_id": server_id,
            "days": code_days,
        },
    )

    return RedeemExecuteResponse(
        code=code_str,
        kind=kind,
        order_id=order_id_val,
        order_no=order_no_val,
        server_id=server_id,
        server_name=target_server_name,
        days=code_days,
        new_expiration_date=new_exp.isoformat(),
    )
