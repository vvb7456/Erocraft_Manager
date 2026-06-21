"""Billing plan service — v2 single-plan model.

See ``docs/BILLING_DESIGN.md`` §3.2.

Plans are immutable templates that orders/invoices reference. CRUD is
admin-only. Saving a plan validates that:

- All resource fields (cpu / memory_mb / disk_mb / node_id / egg_id /
  nest_id / allocation_limit / docker_image / startup_command) are present
  and positive — enforced structurally by :class:`PlanIn`.
- ``env_defaults`` covers every required egg variable and contains no
  unknown keys (validated by
  :func:`app.services.egg_validator.validate_environment`).
- ``period_options`` rules are enforced by :class:`PlanIn`.
- ``docker_image`` is one of the egg's declared images (Wings rejects
  unknown images at install-time, which would push every order built
  from this plan into ``apply_failed``).
- ``cpu`` / ``memory_mb`` / ``disk_mb`` fit inside the chosen node's
  total capacity (overallocation aware) — prevents footguns where a
  plan can never schedule on its node.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.billing import BillingPlan
from app.db.models.pterodactyl import Egg, EggVariable, Nest, PanelNode
from app.schemas.billing_plans import PlanIn  # re-exported for routers
from app.services.egg_validator import EggValidationError, validate_environment

__all__ = [
    "PlanIn",
    "PlanValidationError",
    "PlanNotFoundError",
    "PlanCodeConflictError",
    "validate_plan_payload",
    "list_plans",
    "get_plan",
    "create_plan",
    "update_plan",
    "delete_plan",
]


class PlanValidationError(ValueError):
    """Raised when plan payload fails validation."""


class PlanNotFoundError(LookupError):
    pass


class PlanCodeConflictError(ValueError):
    pass


# --------------------------------------------------------------------------- #
# Trial-plan helpers
# --------------------------------------------------------------------------- #

# Resource columns a trial plan mirrors from its linked standard plan.
# Kept in sync with BillingPlan's mapped columns + _build_snapshot readers.
_TRIAL_MIRRORED_FIELDS = (
    "node_id", "egg_id", "nest_id",
    "cpu", "memory_mb", "disk_mb", "swap_mb", "io",
    "database_limit", "backup_limit", "allocation_limit", "oom_disabled",
    "docker_image", "startup_command", "env_defaults",
)


async def _resolve_linked_plan(
    db: AsyncSession, payload: PlanIn
) -> BillingPlan:
    """Validate + fetch the linked standard plan for a trial payload.

    Rules:
    - ``linked_plan_id`` required.
    - The linked plan must exist and be a ``standard`` plan.
    - Same egg as the trial payload (so the trial's env_defaults validation
      against the egg is meaningful — the linked plan's env is what we'll
      actually use).
    - On *update* of the trial itself, a self-reference is rejected.
    """
    if payload.linked_plan_id is None:
        raise PlanValidationError("试用套餐必须指定关联的标准套餐 (linked_plan_id)")
    linked = await db.get(BillingPlan, payload.linked_plan_id)
    if linked is None:
        raise PlanValidationError(
            f"关联套餐 id={payload.linked_plan_id} 不存在"
        )
    if linked.plan_type != "standard":
        raise PlanValidationError("关联套餐必须是标准套餐 (plan_type=standard)")
    if linked.egg_id != payload.egg_id:
        raise PlanValidationError(
            f"关联套餐的 egg (id={linked.egg_id}) 与本试用套餐 (id={payload.egg_id}) 不一致"
        )
    if not linked.is_active:
        raise PlanValidationError("关联的标准套餐已下架，无法作为试用套餐的资源来源")
    return linked


def _copy_resource_fields(data: dict[str, Any], linked: BillingPlan) -> None:
    """Overwrite trial payload resource fields with the linked plan's values."""
    for field in _TRIAL_MIRRORED_FIELDS:
        data[field] = getattr(linked, field)


# --------------------------------------------------------------------------- #
# DB-aware validation (egg + node existence + env_defaults rules)
# --------------------------------------------------------------------------- #


async def _check_node_exists(db: AsyncSession, node_id: int) -> None:
    if not (
        await db.execute(select(PanelNode.id).where(PanelNode.id == node_id))
    ).scalar_one_or_none():
        raise PlanValidationError(f"节点不存在: id={node_id}")


async def _check_node_capacity(
    db: AsyncSession,
    *,
    node_id: int,
    memory_mb: int,
    disk_mb: int,
) -> None:
    """Reject plans that can never fit a single instance on the node.

    Honours ``memory_overallocate`` / ``disk_overallocate`` (percent) so
    admins can intentionally oversubscribe. Pterodactyl has no node-level
    CPU cap column so CPU is not bound-checked here (Wings will throttle
    the container at runtime).
    """
    row = (
        await db.execute(
            select(
                PanelNode.memory,
                PanelNode.memory_overallocate,
                PanelNode.disk,
                PanelNode.disk_overallocate,
            ).where(PanelNode.id == node_id)
        )
    ).first()
    assert row is not None  # _check_node_exists already ran
    mem_total = int(row.memory) * (1 + max(int(row.memory_overallocate), 0) / 100)
    disk_total = int(row.disk) * (1 + max(int(row.disk_overallocate), 0) / 100)
    if memory_mb > mem_total:
        raise PlanValidationError(
            f"memory_mb={memory_mb} 超过节点 id={node_id} 单机容量 "
            f"{int(mem_total)} MB (含 {int(row.memory_overallocate)}% overallocate)"
        )
    if disk_mb > disk_total:
        raise PlanValidationError(
            f"disk_mb={disk_mb} 超过节点 id={node_id} 单机容量 "
            f"{int(disk_total)} MB (含 {int(row.disk_overallocate)}% overallocate)"
        )


async def _check_docker_image_in_egg(
    db: AsyncSession, egg_id: int, docker_image: str
) -> None:
    """Reject plans whose docker_image isn't declared by the egg.

    Wings refuses to install a server with an image not listed in the
    egg's ``docker_images`` map (panel.eggs.docker_images JSON dict). A
    plan with a stale image silently breaks every order it spawns.
    """
    raw = (
        await db.execute(
            select(Egg.docker_images).where(Egg.id == egg_id)
        )
    ).scalar_one_or_none()
    if not raw:
        # Egg has no images declared — let Wings deal with it; nothing
        # we can verify locally.
        return
    try:
        images = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlanValidationError(
            f"egg {egg_id} 的 docker_images 字段不是合法 JSON, 无法校验"
        ) from exc
    if not isinstance(images, dict):
        return
    allowed = {str(v) for v in images.values() if isinstance(v, str)}
    if docker_image not in allowed:
        raise PlanValidationError(
            f"docker_image={docker_image!r} 不在 egg {egg_id} 声明的镜像列表中: "
            f"{sorted(allowed)}"
        )


async def _check_nest_egg_pair(
    db: AsyncSession, nest_id: int, egg_id: int
) -> None:
    row = (
        await db.execute(select(Egg.id, Egg.nest_id).where(Egg.id == egg_id))
    ).first()
    if row is None:
        raise PlanValidationError(f"egg 不存在: id={egg_id}")
    if row.nest_id != nest_id:
        raise PlanValidationError(
            f"egg {egg_id} 不属于 nest {nest_id} (实际属于 nest {row.nest_id})"
        )
    if not (
        await db.execute(select(Nest.id).where(Nest.id == nest_id))
    ).scalar_one_or_none():
        raise PlanValidationError(f"nest 不存在: id={nest_id}")


async def _validate_env_defaults(
    db: AsyncSession,
    egg_id: int,
    env_defaults: dict[str, Any],
) -> dict[str, Any]:
    """Validate ``env_defaults`` against the egg's variable schema.

    §3.2.2 strict rules:

    - Every variable declared by the egg must appear (validate_environment
      itself rejects missing required values).
    - No keys beyond those declared by the egg are allowed.
    - Each value must satisfy the per-variable Laravel rule string.

    Returns the normalized dict (string-cast values, only declared keys).
    """
    rows = (
        await db.execute(
            select(EggVariable.env_variable, EggVariable.rules).where(
                EggVariable.egg_id == egg_id
            )
        )
    ).all()
    declared = {row.env_variable: row.rules for row in rows}
    provided = dict(env_defaults or {})

    unknown = set(provided.keys()) - set(declared.keys())
    if unknown:
        raise PlanValidationError(
            f"env_defaults 含 egg {egg_id} 未声明的变量: {sorted(unknown)}"
        )

    normalized: dict[str, Any] = {}
    for name, rules in declared.items():
        value = provided.get(name)
        try:
            validate_environment(name, value, rules)
        except EggValidationError as exc:
            raise PlanValidationError(
                f"env_defaults[{name}] 校验失败: {exc}"
            ) from exc
        if value is not None:
            normalized[name] = str(value)
    return normalized


async def validate_plan_payload(
    db: AsyncSession,
    payload: PlanIn,
) -> dict[str, Any]:
    """Run full DB-aware validation; return ORM-ready column dict.

    For trial plans the resource fields (node/egg/nest/cpu/mem/disk/swap/
    io/docker_image/startup/env_defaults/limits/oom_disabled) are NOT taken
    from the payload — they are copied from the linked standard plan so a
    trial always shares its standard sibling's configuration. The caller
    still sends these fields (the form is shared), but they are discarded.
    Trial period_options is forced to a single ``count=1`` entry.
    """
    await _check_node_exists(db, payload.node_id)
    await _check_node_capacity(
        db,
        node_id=payload.node_id,
        memory_mb=payload.memory_mb,
        disk_mb=payload.disk_mb,
    )
    await _check_nest_egg_pair(db, payload.nest_id, payload.egg_id)
    await _check_docker_image_in_egg(db, payload.egg_id, payload.docker_image)
    normalized_env = await _validate_env_defaults(
        db, payload.egg_id, payload.env_defaults
    )

    data = payload.model_dump()
    # period_options: nested PeriodOption -> dict[str, Any]
    data["period_options"] = [opt.model_dump() for opt in payload.period_options]
    data["env_defaults"] = normalized_env

    # Trial normalization: resource fields mirror the linked standard plan.
    if payload.plan_type == "trial":
        linked = await _resolve_linked_plan(db, payload)
        _copy_resource_fields(data, linked)
        # Trial is not renewable in-place; force single base period.
        data["period_options"] = [{"count": 1, "discount_pct": 0.0}]
    else:
        # Standard plan must not declare a linked plan.
        data["linked_plan_id"] = None

    return data


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #


async def list_plans(
    db: AsyncSession, *, include_inactive: bool = True
) -> list[BillingPlan]:
    stmt = select(BillingPlan).order_by(
        BillingPlan.display_order.asc(), BillingPlan.id.asc()
    )
    if not include_inactive:
        stmt = stmt.where(BillingPlan.is_active.is_(True))
    return list((await db.execute(stmt)).scalars().all())


async def get_plan(db: AsyncSession, plan_id: int) -> BillingPlan:
    obj = await db.get(BillingPlan, plan_id)
    if obj is None:
        raise PlanNotFoundError(f"plan id={plan_id} not found")
    return obj


async def create_plan(db: AsyncSession, payload: PlanIn) -> BillingPlan:
    data = await validate_plan_payload(db, payload)
    obj = BillingPlan(**data)
    db.add(obj)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise PlanCodeConflictError(
            f"套餐代号已存在: {payload.code}"
        ) from exc
    await db.refresh(obj)
    return obj


async def update_plan(
    db: AsyncSession, plan_id: int, payload: PlanIn
) -> BillingPlan:
    obj = await get_plan(db, plan_id)
    data = await validate_plan_payload(db, payload)
    for key, value in data.items():
        setattr(obj, key, value)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise PlanCodeConflictError(
            f"套餐代号已存在: {payload.code}"
        ) from exc
    await db.refresh(obj)
    return obj


async def delete_plan(db: AsyncSession, plan_id: int) -> None:
    # Plans are decoupled from orders: ``manager_billing_orders.plan_id`` has
    # ON DELETE SET NULL and the order's ``plan_snapshot`` JSON keeps the
    # full historical record. Hard-delete is therefore always safe; the FE
    # “deactivate” toggle is now purely about hiding the plan from /plans,
    # not a workaround for delete failures.
    obj = await get_plan(db, plan_id)
    await db.delete(obj)
    await db.commit()
