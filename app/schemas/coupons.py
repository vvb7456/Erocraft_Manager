"""Pydantic schemas for coupon templates + coupons.

See ``docs/REFERRAL_AND_COUPON_DESIGN.md`` §5 / §7.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Forbid(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── Templates ────────────────────────────────────────────────────────────


class CouponTemplateIn(_Forbid):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    discount_fen: int = Field(gt=0)
    description: str | None = Field(default=None, max_length=2000)
    min_order_fen: int = Field(default=0, ge=0)
    valid_days: int = Field(default=30, gt=0, le=3650)
    applicable_plan_ids: list[int] | None = None
    applicable_order_kinds: list[str] | None = None
    is_active: bool = True


class CouponTemplateUpdate(_Forbid):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    discount_fen: int | None = Field(default=None, gt=0)
    min_order_fen: int | None = Field(default=None, ge=0)
    valid_days: int | None = Field(default=None, gt=0, le=3650)
    applicable_plan_ids: list[int] | None = None
    applicable_order_kinds: list[str] | None = None
    is_active: bool | None = None


class CouponTemplateOut(BaseModel):
    id: int
    code: str
    name: str
    description: str | None
    discount_fen: int
    min_order_fen: int
    valid_days: int
    applicable_plan_ids: list[int] | None
    applicable_order_kinds: list[str] | None
    is_active: bool
    is_builtin: bool
    created_at: str
    updated_at: str


# ── Coupons ──────────────────────────────────────────────────────────────


class CouponOut(BaseModel):
    id: int
    code: str
    template_id: int
    template_name: str | None = None
    user_id: int
    status: str
    source: str
    discount_fen: int
    min_order_fen: int
    applicable_plan_ids: list[int] | None
    applicable_order_kinds: list[str] | None
    issued_at: str
    expires_at: str
    used_at: str | None
    used_order_id: int | None
    actual_discount_fen: int | None
    reserved_order_id: int | None
    reserved_at: str | None
    revoked_at: str | None
    revoke_reason: str | None


class ManualGrantRequest(_Forbid):
    user_id: int = Field(gt=0)
    template_id: int = Field(gt=0)


class RevokeCouponRequest(_Forbid):
    reason: str | None = Field(default=None, max_length=200)


class CouponListResponse(BaseModel):
    items: list[CouponOut]
    total: int


class CouponPreviewResponse(BaseModel):
    """Discount preview for the checkout modal."""

    applicable: bool
    discount_fen: int = 0
    reason: str | None = None
