"""Audit logging helpers for the FastAPI backend."""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.manager import ManagerActivityLog

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
        "other",
    }
)

_STATUS_MAP = {
    "success": "success",
    "ok": "success",          # legacy alias used by some routers
    "failure": "failed",
    "fail": "failed",
    "error": "failed",
    "failed": "failed",
    "partial": "partial",
    "warning": "partial",     # legacy alias
    "info": "info",
}


def _normalize_status(status: str) -> str:
    return _STATUS_MAP.get(status, "info")


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
    status: str,
    detail_key: str,
    detail_params: Mapping[str, Any] | None = None,
) -> None:
    try:
        db.add(
            ManagerActivityLog(
                actor=actor[:100],
                category=_normalize_category(category)[:32],
                status=_normalize_status(status)[:50],
                detail_key=detail_key[:120],
                detail_params=json.dumps(
                    dict(detail_params or {}), ensure_ascii=False, default=str
                ),
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Failed to write manager activity log")
