"""Schemas for manager activity log routes."""

from __future__ import annotations

from pydantic import BaseModel
from typing import Any, Literal


class ActivityLogItem(BaseModel):
    id: int
    timestamp: str | None
    actor: str
    category: str
    status: Literal["success", "failed"]
    detailKey: str | None = None
    detailParams: dict[str, Any] = {}


class ActivityLogFilters(BaseModel):
    actors: list[str]
    categories: list[str]


class ActivityLogsResponse(BaseModel):
    logs: list[ActivityLogItem]
    total: int
    page: int
    perPage: int
    totalPages: int
    filters: ActivityLogFilters
