"""Schemas for manager activity log routes."""

from __future__ import annotations

from pydantic import BaseModel
from typing import Any


class ActivityLogItem(BaseModel):
    id: int
    timestamp: str | None
    actor: str
    action: str
    status: str
    detailKey: str | None = None
    detailParams: dict[str, Any] = {}


class ActivityLogFilters(BaseModel):
    actors: list[str]
    actions: list[str]


class ActivityLogsResponse(BaseModel):
    logs: list[ActivityLogItem]
    total: int
    page: int
    perPage: int
    totalPages: int
    filters: ActivityLogFilters
