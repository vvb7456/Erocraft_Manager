"""Pydantic schemas for the admin allocation endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ServerBrief(BaseModel):
    id: int
    uuid_short: str
    name: str
    owner_id: int
    owner_name: str | None = None


class AllocationOut(BaseModel):
    id: int
    ip: str
    alias: str | None = None
    port: int
    notes: str | None = None
    server: ServerBrief | None = None


class AllocationSummary(BaseModel):
    total: int
    assigned: int
    unassigned: int


class AllocationListResponse(BaseModel):
    items: list[AllocationOut]
    page: int
    per_page: int
    total: int
    summary: AllocationSummary


class AllocationCreateIn(BaseModel):
    ip: str = Field(min_length=1, max_length=191)
    alias: str | None = Field(default=None, max_length=191)
    ports: str = Field(min_length=1)


class AllocationSkip(BaseModel):
    port: int
    reason: str


class AllocationCreateResponse(BaseModel):
    created: list[AllocationOut]
    skipped: list[AllocationSkip]


class AllocationUpdateIn(BaseModel):
    alias: str | None = None
    # DB column allocations.notes is varchar(191) despite Panel PHP model saying max:256
    notes: str | None = None

    @field_validator("alias")
    @classmethod
    def _validate_alias(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if len(s) > 191:
            raise ValueError("IP 别名长度不能超过 191")
        return s or None

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if len(s) > 191:
            raise ValueError("端口备注长度不能超过 191")
        return s or None


class AllocationBulkDeleteIn(BaseModel):
    ids: list[int] = Field(min_length=1)
