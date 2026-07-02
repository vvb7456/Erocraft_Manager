"""Admin routes for billing plan CRUD."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.db.models.billing import BillingPlan
from app.db.models.pterodactyl import PteroUser
from app.schemas.settings import SettingsMessageResponse
from app.services.audit import log_manager_activity
from app.services.billing.plans import (
    PlanCodeConflictError,
    PlanIn,
    PlanNotFoundError,
    PlanValidationError,
    create_plan,
    delete_plan,
    get_plan,
    list_plans,
    update_plan,
)

router = APIRouter(prefix="/admin/billing/plans", tags=["billing"])


def _serialize(plan: BillingPlan) -> dict[str, Any]:
    return {
        "id": plan.id,
        "code": plan.code,
        "display_name": plan.display_name,
        "price_fen": plan.price_fen,
        "days": plan.days,
        "currency_code": plan.currency_code,
        "period_options": plan.period_options,
        "node_id": plan.node_id,
        "egg_id": plan.egg_id,
        "nest_id": plan.nest_id,
        "cpu": plan.cpu,
        "memory_mb": plan.memory_mb,
        "disk_mb": plan.disk_mb,
        "swap_mb": plan.swap_mb,
        "io": plan.io,
        "database_limit": plan.database_limit,
        "backup_limit": plan.backup_limit,
        "allocation_limit": plan.allocation_limit,
        "oom_disabled": plan.oom_disabled,
        "docker_image": plan.docker_image,
        "startup_command": plan.startup_command,
        "env_defaults": plan.env_defaults,
        "is_active": plan.is_active,
        "display_order": plan.display_order,
        "description_md": plan.description_md,
        "category_label": plan.category_label,
        "plan_type": plan.plan_type,
        "linked_plan_id": plan.linked_plan_id,
        "llm_enabled": plan.llm_enabled,
        "llm_quota_grant": plan.llm_quota_grant,
        "llm_model_limits": plan.llm_model_limits,
        "created_at": plan.created_at.isoformat() + "Z",
        "updated_at": plan.updated_at.isoformat() + "Z",
    }


@router.get("")
async def plans_list(
    include_inactive: bool = True,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    plans = await list_plans(db, include_inactive=include_inactive)
    return [_serialize(p) for p in plans]


@router.get("/{plan_id}")
async def plans_get(
    plan_id: int,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        plan = await get_plan(db, plan_id)
    except PlanNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _serialize(plan)


@router.post("", status_code=status.HTTP_201_CREATED)
async def plans_create(
    payload: PlanIn,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        plan = await create_plan(db, payload)
    except PlanValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
        ) from exc
    except PlanCodeConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="billing",
        status="success",
        detail_key="billing.plan.create",
        detail_params={
            "plan_id": plan.id,
            "code": plan.code,
            "display_name": plan.display_name,
        },
    )
    return _serialize(plan)


@router.put("/{plan_id}")
async def plans_update(
    plan_id: int,
    payload: PlanIn,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        plan = await update_plan(db, plan_id, payload)
    except PlanNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except PlanValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
        ) from exc
    except PlanCodeConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="billing",
        status="success",
        detail_key="billing.plan.update",
        detail_params={
            "plan_id": plan.id,
            "code": plan.code,
            "display_name": plan.display_name,
        },
    )
    return _serialize(plan)


@router.delete("/{plan_id}", response_model=SettingsMessageResponse)
async def plans_delete(
    plan_id: int,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SettingsMessageResponse:
    try:
        await delete_plan(db, plan_id)
    except PlanNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except PlanValidationError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="billing",
        status="success",
        detail_key="billing.plan.delete",
        detail_params={"plan_id": plan_id},
    )
    return SettingsMessageResponse(message=f"已删除套餐 id={plan_id}")
