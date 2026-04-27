"""Admin activity log routes."""

from __future__ import annotations

import math
import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.db.models.pterodactyl import PteroUser
from app.db.repositories.activity_logs import activity_log_repository
from app.schemas.logs import ActivityLogFilters, ActivityLogItem, ActivityLogsResponse

router = APIRouter(prefix="/admin", tags=["logs"])


@router.get("/activity-logs", response_model=ActivityLogsResponse)
async def activity_logs(
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=1, le=100),
    actor: str | None = None,
    category: str | None = None,
    action: str | None = None,
    status: str | None = None,
    host_id: int | None = Query(default=None),
    node_id: int | None = Query(default=None),
) -> ActivityLogsResponse:
    logs, total = await activity_log_repository.list_manager_logs(
        db,
        page=page,
        per_page=per_page,
        actor=actor,
        category=category,
        action=action,
        status=status,
        host_id=host_id,
        node_id=node_id,
    )
    actors = await activity_log_repository.distinct_actors(db)
    categories = await activity_log_repository.distinct_categories(db)
    actions = await activity_log_repository.distinct_actions(db)

    def _detail_params(raw: str | None) -> dict[str, object]:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    return ActivityLogsResponse(
        logs=[
            ActivityLogItem(
                id=log.id,
                timestamp=log.timestamp.isoformat() if log.timestamp else None,
                actor=log.actor,
                category=log.category,
                action=log.action,
                status=log.status,
                detailKey=log.detail_key,
                detailParams=_detail_params(log.detail_params),
            )
            for log in logs
        ],
        total=total,
        page=page,
        perPage=per_page,
        totalPages=max(1, math.ceil(total / per_page)) if per_page else 1,
        filters=ActivityLogFilters(
            actors=actors,
            categories=categories,
            actions=actions,
        ),
    )
