"""Pydantic schemas for the admin allocation endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


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


class AllocationBulkDeleteIn(BaseModel):
    ids: list[int] = Field(min_length=1)
