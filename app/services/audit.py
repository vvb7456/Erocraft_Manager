"""Audit logging helpers for the FastAPI backend."""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.manager import ManagerActivityLog
from app.core.contracts import OperationResult

logger = logging.getLogger(__name__)


# Allowed normalized category values. Anything else falls back to "other".
_VALID_CATEGORIES: frozenset[str] = frozenset(
    {
        "auth",
        "server",
        "user",
        "host_node",
        "automation",
        "settings",
        "certificate",
        "email",
        "tunnel",
        "billing",
        "monitoring",
        "other",
    }
)


def _normalize_category(category: str | None) -> str:
    if not category:
        return "other"
    c = category.strip().lower()
    return c if c in _VALID_CATEGORIES else "other"


async def log_manager_activity(
    db: AsyncSession,
    *,
    actor: str,
    category: str | None = None,
    operation: OperationResult,
    detail_key: str,
    detail_params: Mapping[str, Any] | None = None,
) -> None:
    try:
        params = dict(detail_params or {})
        params["operation"] = operation.model_dump(exclude_none=True, exclude_defaults=True)
        db.add(
            ManagerActivityLog(
                actor=actor[:100],
                category=_normalize_category(category)[:32],
                status=operation.outcome,
                detail_key=detail_key[:120],
                detail_params=json.dumps(
                    params, ensure_ascii=False, default=str
                ),
            )
        )
        from app.services.notifications.events import audit_failure

        await audit_failure(
            db, actor=actor, category=_normalize_category(category), operation=operation,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Failed to write manager activity log")
