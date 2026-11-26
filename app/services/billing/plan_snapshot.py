from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.db.models.billing import BillingPlan

PLAN_SNAPSHOT_SCHEMA_VERSION = 2

_PLAN_SNAPSHOT_FIELDS: tuple[str, ...] = (
    "price_fen", "days", "currency_code", "egg_id", "nest_id", "node_id",
    "docker_image", "startup_command", "cpu", "memory_mb", "disk_mb", "swap_mb",
    "io", "database_limit", "backup_limit", "allocation_limit", "oom_disabled",
    "plan_type", "linked_plan_id", "llm_enabled", "llm_quota_grant",
    "newapi_plan_id", "llm_group",
)


def build_plan_snapshot(
    plan: BillingPlan,
    *,
    period: Mapping[str, Any] | None = None,
    total_fen: int | None = None,
    total_days: int | None = None,
    previous_plan: BillingPlan | None = None,
) -> dict[str, Any]:
    selected_period: dict[str, Any] = dict(period) if period is not None else {"count": 1, "discount_pct": 0}
    selected_period["total_fen"] = plan.price_fen if total_fen is None else total_fen
    selected_period["total_days"] = plan.days if total_days is None else total_days

    snapshot: dict[str, Any] = {
        "schema_version": PLAN_SNAPSHOT_SCHEMA_VERSION,
        "plan_id": plan.id,
        "plan_name": plan.display_name,
        "plan_code": plan.code,
        **{key: getattr(plan, key) for key in _PLAN_SNAPSHOT_FIELDS},
        "env_snapshot": dict(plan.env_defaults or {}),
        "selected_period": selected_period,
    }
    if previous_plan is not None:
        snapshot["previous_plan"] = {
            "plan_id": previous_plan.id,
            "plan_code": previous_plan.code,
            "plan_name": previous_plan.display_name,
            "price_fen": previous_plan.price_fen,
            "days": previous_plan.days,
        }
    return snapshot


__all__ = ["PLAN_SNAPSHOT_SCHEMA_VERSION", "build_plan_snapshot"]
