"""Public plan listing for end users — see ``BILLING_DESIGN.md`` §6.

Endpoints:

* ``GET /api/user/plans``        — active-only plan list.
* ``GET /api/user/plans/{id}``   — fetch a single plan by ID without
  filtering on ``is_active`` (used by the renewal flow: a server bound
  to a deactivated plan must still be renewable).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.core.time import to_iso_z
from app.db.models.billing import BillingPlan
from app.db.models.pterodactyl import PteroUser
from app.services.billing.plans import list_plans

router = APIRouter(prefix="/user/plans", tags=["billing"])


class _Forbid(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublicPeriodOption(_Forbid):
    count: int
    discount_pct: float


class PublicPlanOut(_Forbid):
    """Public-facing plan projection.

    Excludes server-creation internals (``startup_command``, ``env_defaults``,
    ``oom_disabled``, ``swap_mb``, ``io``, ``database_limit``,
    ``backup_limit``, ``allocation_limit``, ``nest_id``, ``egg_id``,
    ``docker_image``) — those are admin/template concerns; the user only
    needs to compare offerings.
    """

    id: int
    code: str
    display_name: str
    price_fen: int
    days: int
    currency_code: str
    period_options: list[PublicPeriodOption]
    cpu: int
    memory_mb: int
    disk_mb: int
    description_md: str | None
    category_label: str | None
    display_order: int
    plan_type: str = "standard"
    linked_plan_id: int | None = None
    llm_enabled: bool = False
    llm_quota_grant: int = 0
    llm_model_limits: str | None = None
    created_at: str
    updated_at: str


def _serialize(plan: BillingPlan) -> PublicPlanOut:
    return PublicPlanOut(
        id=plan.id,
        code=plan.code,
        display_name=plan.display_name,
        price_fen=plan.price_fen,
        days=plan.days,
        currency_code=plan.currency_code,
        period_options=[
            PublicPeriodOption(count=int(o["count"]), discount_pct=float(o["discount_pct"]))
            for o in (plan.period_options or [])
        ],
        cpu=plan.cpu,
        memory_mb=plan.memory_mb,
        disk_mb=plan.disk_mb,
        description_md=plan.description_md,
        category_label=plan.category_label,
        display_order=plan.display_order,
        plan_type=plan.plan_type,
        linked_plan_id=plan.linked_plan_id,
        llm_enabled=plan.llm_enabled,
        llm_quota_grant=plan.llm_quota_grant,
        llm_model_limits=plan.llm_model_limits,
        created_at=to_iso_z(plan.created_at),
        updated_at=to_iso_z(plan.updated_at),
    )


@router.get("", response_model=list[PublicPlanOut])
async def list_public_plans_endpoint(
    _: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PublicPlanOut]:
    plans = await list_plans(db, include_inactive=False)
    return [_serialize(p) for p in plans]


@router.get("/{plan_id}", response_model=PublicPlanOut)
async def get_plan_endpoint(
    plan_id: int,
    _: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PublicPlanOut:
    """Fetch a single plan by ID without filtering on ``is_active``.

    Used by the renewal flow: a server bound to a deactivated plan
    must still be renewable. The backend service layer in
    ``services/billing/orders.py`` mirrors this — it explicitly does
    NOT check ``is_active`` for renewals.
    """
    plan = await db.get(BillingPlan, plan_id)
    if plan is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="套餐不存在",
        )
    return _serialize(plan)
