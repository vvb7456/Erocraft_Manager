"""Schemas for admin server management routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
    planId: int | None = None
    planCode: str | None = None
    planName: str | None = None


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


class RenewServerRequest(BaseModel):
    date: str


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
