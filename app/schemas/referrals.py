"""Pydantic schemas for the referral (invite) system."""

from __future__ import annotations

from pydantic import BaseModel


class InviteCodeOut(BaseModel):
    code: str
    invite_url: str | None = None
    disabled: bool = False
    created_at: str | None = None


class ReferralOut(BaseModel):
    id: int
    inviter_user_id: int
    invitee_user_id: int
    invitee_username: str | None = None
    invitee_email: str | None = None
    invite_code: str
    status: str
    qualifying_order_id: int | None = None
    rewarded_at: str | None = None
    inviter_coupon_id: int | None = None
    invitee_coupon_id: int | None = None
    created_at: str


class ReferralListResponse(BaseModel):
    items: list[ReferralOut]
    total: int


class RewardPreview(BaseModel):
    """Public-facing preview of what an invite redemption is worth.

    Resolved from runtime settings + the active coupon templates. ``enabled``
    is False when the operator has turned off referral rewards OR either
    template is missing/inactive; in that case the numeric fields are still
    populated with best-effort defaults but the UI should hide reward copy.
    """
    enabled: bool
    qualifying_min_fen: int
    inviter_discount_fen: int | None = None
    invitee_discount_fen: int | None = None
    inviter_valid_days: int | None = None
    invitee_valid_days: int | None = None
    inviter_min_order_fen: int | None = None
    invitee_min_order_fen: int | None = None


class InviteSummaryResponse(BaseModel):
    invite: InviteCodeOut
    stats: dict[str, int]
    recent: list[ReferralOut]
    reward: RewardPreview | None = None
