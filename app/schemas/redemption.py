"""Pydantic schemas for redemption batches, exports, codes, and Agiso pull API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


RedemptionChannel = Literal["taobao", "xianyu", "other"]
RedemptionKind = Literal["new_purchase", "renew", "convert"]


def _to_utc_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class RedemptionBatchCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    plan_id: int = Field(gt=0)
    days: int = Field(ge=1, le=3650)
    amount_fen: int = Field(ge=0, le=100_000_000)
    channel: RedemptionChannel = "taobao"
    quantity: int = Field(ge=1, le=1000)
    expires_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("批次名称不能为空")
        return s

    @field_validator("expires_at")
    @classmethod
    def _normalize_expires_at(cls, v: datetime | None) -> datetime | None:
        return _to_utc_naive(v)


class RedemptionExportOut(BaseModel):
    id: int
    batch_id: int
    quantity: int
    created_by: int | None = None
    created_by_username: str | None = None
    created_at: str


class RedemptionBatchOut(BaseModel):
    id: int
    name: str
    source: str
    spec_key: str | None = None
    plan_id: int | None = None
    plan_name: str | None = None
    plan_code: str | None = None
    days: int
    amount_fen: int
    channel: str
    quantity: int
    unused_count: int = 0
    redeemed_count: int = 0
    void_count: int = 0
    expired_count: int = 0
    exported_count: int = 0
    exportable_count: int = 0
    expires_at: str | None = None
    created_by: int | None = None
    created_by_username: str | None = None
    created_at: str


class RedemptionBatchDetailOut(RedemptionBatchOut):
    exports: list[RedemptionExportOut] = Field(default_factory=list)


class RedemptionBatchListResponse(BaseModel):
    items: list[RedemptionBatchOut]
    total: int


class RedemptionExportCreateRequest(BaseModel):
    quantity: int | None = Field(default=None, ge=1, le=5000)


class RedemptionVoidRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class RedemptionBatchVoidOut(BaseModel):
    batch_id: int
    voided_count: int


class RedemptionCodeOut(BaseModel):
    id: int
    code: str
    batch_id: int
    batch_name: str | None = None
    source: str = "manual"
    plan_id: int | None = None
    plan_name: str | None = None
    days: int
    amount_fen: int
    channel: str
    status: str
    export_id: int | None = None
    external_order_id: str | None = None
    redeemed_by: int | None = None
    redeemed_by_username: str | None = None
    redeemed_at: str | None = None
    order_id: int | None = None
    order_no: str | None = None
    target_server_id: int | None = None
    target_server_name: str | None = None
    expires_at: str | None = None
    voided_at: str | None = None
    void_reason: str | None = None
    created_at: str


class RedemptionCodeListResponse(BaseModel):
    items: list[RedemptionCodeOut]
    total: int


class AgisoIssueRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    plan_code: str = Field(
        min_length=1,
        max_length=64,
        validation_alias=AliasChoices("planCode", "plan_code", "productCode", "product_code"),
    )
    period_count: int = Field(
        default=1,
        ge=1,
        le=120,
        validation_alias=AliasChoices("periodCount", "period_count", "period"),
    )
    num: int = Field(
        default=1,
        ge=1,
        le=50,
        validation_alias=AliasChoices("num", "quantity", "count"),
    )
    order_id: str | None = Field(
        default=None,
        max_length=56,
        validation_alias=AliasChoices("orderId", "order_id", "tid", "externalOrderId"),
    )
    amount_yuan: float | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("amountYuan", "amount_yuan", "payment"),
    )
    channel: RedemptionChannel | None = None

    @field_validator("plan_code", mode="before")
    @classmethod
    def _clean_plan_code(cls, v: Any) -> str:
        return str(v or "").strip()

    @field_validator("period_count", "num", mode="before")
    @classmethod
    def _clean_positive_int(cls, v: Any) -> Any:
        if v is None or v == "":
            return 1
        if isinstance(v, str):
            s = v.strip()
            if not s or s.startswith("{$"):
                return 1
            return int(s)
        return v

    @field_validator("order_id", mode="before")
    @classmethod
    def _clean_order_id(cls, v: Any) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        if not s or s.startswith("{$"):
            return None
        return s[:56]

    @field_validator("amount_yuan", mode="before")
    @classmethod
    def _clean_amount_yuan(cls, v: Any) -> float | None:
        if v is None or v == "":
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s or s.startswith("{$"):
                return None
            try:
                return float(s)
            except ValueError:
                return None
        return v


class AgisoCardItem(BaseModel):
    cardNo: str
    cardPwd: str = ""


class AgisoIssueData(BaseModel):
    cardNo: str
    cards: list[AgisoCardItem]
    planCode: str
    periodCount: int
    orderId: str | None = None
    quantity: int
    days: int
    expiresAt: str | None = None


class AgisoIssueResponse(BaseModel):
    code: int = 0
    msg: str = "ok"
    data: AgisoIssueData


class RedeemPreviewRequest(BaseModel):
    code: str = Field(min_length=4, max_length=64)


class RedeemCompatibleServerOut(BaseModel):
    id: int
    name: str
    kind: Literal["renew", "convert"]
    is_trial: bool
    is_suspended: bool
    current_expiration_date: str | None = None
    projected_expiration_date: str


class RedeemPlanSummaryOut(BaseModel):
    id: int
    code: str
    display_name: str
    cpu: int
    memory_mb: int
    disk_mb: int
    llm_enabled: bool
    llm_quota_grant: int


class RedeemPreviewResponse(BaseModel):
    code: str
    days: int
    expires_at: str | None = None
    plan: RedeemPlanSummaryOut
    new_server_expiration_date: str
    compatible_servers: list[RedeemCompatibleServerOut]
    already_redeemed_by_me: bool = False
    order_id: int | None = None
    order_no: str | None = None
    target_server_id: int | None = None


class RedeemExecuteRequest(BaseModel):
    code: str = Field(min_length=4, max_length=64)
    target_server_id: int | None = Field(default=None, gt=0)


class RedeemExecuteResponse(BaseModel):
    code: str
    kind: RedemptionKind
    order_id: int
    order_no: str
    server_id: int
    server_name: str
    days: int
    new_expiration_date: str
