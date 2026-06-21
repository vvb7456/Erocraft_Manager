"""Schemas for billing plans (``manager_billing_plans``).

See ``docs/BILLING_DESIGN.md`` §3.2. v2 single-plan model: plans no longer
carry a ``kind`` field — the same plan supports both new-purchase and renew
via the order-level ``kind``. Resource fields are mandatory on every plan.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Forbid(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PeriodOption(_Forbid):
    """One purchasable period multiplier on a plan.

    ``count`` is the number of base periods bought; ``discount_pct`` is the
    flat percentage discount applied to ``price_fen * count`` at order time.
    """

    count: int = Field(ge=1, le=24)
    discount_pct: float = Field(ge=0, le=50)


class PlanIn(_Forbid):
    """Create / update payload for ``manager_billing_plans``.

    Cross-field rules — see ``BILLING_DESIGN.md`` §3.2 / §3.2.1 / §3.2.2:

    * ``period_options`` non-empty, contains exactly one entry per ``count``,
      and **must** include ``count == 1`` (with ``discount_pct == 0``).
    * All resource fields are required and positive.
    * ``env_defaults`` is validated against the egg's variable schema in
      :func:`app.services.billing.plans.validate_plan_payload` (DB-aware).
    """

    code: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    price_fen: int = Field(gt=0, le=10_000_000)
    days: int = Field(gt=0, le=3650)
    currency_code: str = Field(default="CNY", min_length=3, max_length=3)

    period_options: list[PeriodOption] = Field(min_length=1, max_length=12)

    # Resource / runtime spec — mandatory on every plan in v2.
    node_id: int = Field(gt=0)
    egg_id: int = Field(gt=0)
    nest_id: int = Field(gt=0)
    cpu: int = Field(gt=0, le=1_000_000)
    memory_mb: int = Field(gt=0, le=1_000_000)
    disk_mb: int = Field(gt=0, le=10_000_000)
    swap_mb: int = Field(default=0, ge=-1, le=1_000_000)
    io: int = Field(default=500, ge=10, le=1000)
    database_limit: int = Field(default=0, ge=0, le=1000)
    backup_limit: int = Field(default=0, ge=0, le=1000)
    allocation_limit: int = Field(default=1, gt=0, le=1000)
    oom_disabled: bool = True
    docker_image: str = Field(min_length=1, max_length=255)
    startup_command: str = Field(min_length=1)
    env_defaults: dict[str, Any] = Field(default_factory=dict)

    is_active: bool = True
    display_order: int = Field(default=0, ge=0, le=10_000)
    description_md: str | None = None
    category_label: str | None = Field(default=None, max_length=64)

    # Trial-plan support (20260619_trial). ``plan_type`` defaults to
    # ``standard``. When ``trial``: ``linked_plan_id`` MUST point at a
    # standard plan with the same egg; the trial's resource fields are
    # ignored on save and copied from the linked plan instead, and
    # ``period_options`` is forced to a single ``count=1`` entry (trial
    # is not renewable in-place, only convertible).
    plan_type: str = Field(default="standard", pattern=r"^(standard|trial)$")
    linked_plan_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _check_period_options(self) -> "PlanIn":
        seen: set[int] = set()
        has_base = False
        for opt in self.period_options:
            if opt.count in seen:
                raise ValueError(f"period_options 中 count={opt.count} 重复")
            seen.add(opt.count)
            if opt.count == 1:
                has_base = True
                if opt.discount_pct != 0:
                    raise ValueError(
                        "period_options 中 count=1 的项 discount_pct 必须为 0"
                    )
        if not has_base:
            raise ValueError("period_options 必须含一项 count=1 的基础周期")
        return self
