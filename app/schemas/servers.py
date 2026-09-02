"""Schemas for admin server management routes."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ServerListItem(BaseModel):
    pteroId: int
    uuid: str | None
    name: str
    ownerId: int | None
    ownerUsername: str | None
    ownerEmail: str | None = None
    eggName: str | None
    expirationDate: str | None
    daysLeft: int | None
    statusLabel: str
    isSuspended: bool
    isTrial: bool = False
    planId: int | None = None
    planCode: str | None = None
    planName: str | None = None
    planType: str | None = None


class ServersListResponse(BaseModel):
    servers: list[ServerListItem]


class CreateServerRequest(BaseModel):
    user_id: int
    server_name: str = Field(min_length=1)
    egg_id: int
    startup_command: str = Field(min_length=1)
    node_id: int
    allocation_id: int
    expiration_days: int = Field(ge=1, le=3650)
    docker_image: str = ""
    environment: dict[str, str] = Field(default_factory=dict)
    cpu: int | None = None
    memory: int | None = None
    disk: int | None = None
    databases: int | None = None
    backups: int | None = None
    allocations: int | None = None
    plan_id: int | None = None
    channel: Literal["taobao", "xianyu", "other"] = "taobao"
    external_order_id: str | None = None
    amount_yuan: float | None = None
    channel_note: str | None = None

    @model_validator(mode="after")
    def validate_channel_fields(self) -> Self:
        if self.channel in ("taobao", "xianyu"):
            if self.plan_id is None:
                raise ValueError("电商渠道开通必须选择套餐")
            if not (self.external_order_id or "").strip():
                raise ValueError("电商渠道开通必须填写外部订单号")
            if self.amount_yuan is None or self.amount_yuan <= 0:
                raise ValueError("电商渠道开通必须填写大于 0 的有效金额")
        return self


class RenewServerRequest(BaseModel):
    # `date` may be null/None to clear the expiration date (i.e. set the
    # server to “permanent”). Existing callers continue to pass a
    # YYYY-MM-DD string for the extend / renew flow.
    date: str | None = None
    channel: Literal["taobao", "xianyu", "other"] = "taobao"
    external_order_id: str | None = None
    amount_yuan: float | None = None
    channel_note: str | None = None

    @model_validator(mode="after")
    def validate_channel_fields(self) -> Self:
        if self.channel in ("taobao", "xianyu"):
            if self.date is None:
                raise ValueError("电商渠道续期必须指定具体到期日")
            if not (self.external_order_id or "").strip():
                raise ValueError("电商渠道续期必须填写外部订单号")
            if self.amount_yuan is None or self.amount_yuan <= 0:
                raise ValueError("电商渠道续期必须填写大于 0 的有效金额")
        return self


class UpdateServerRequest(BaseModel):
    expirationDate: str | None = None


class MessageResponse(BaseModel):
    message: str


class ToggleSuspendResponse(MessageResponse):
    isSuspended: bool


class CreateServerResponse(MessageResponse):
    server: dict[str, Any]


class BatchServersRequest(BaseModel):
    action: Literal["suspend", "unsuspend", "renew", "email", "delete", "update_plan"]
    serverIds: list[int] = Field(min_length=1)
    days: int | None = None
    planId: int | None = None


class UpdateServerPlanRequest(BaseModel):
    planId: int | None = None


class BatchServersResponse(MessageResponse):
    success: int
    failed: int
