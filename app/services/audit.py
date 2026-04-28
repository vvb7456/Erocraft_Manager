"""Audit logging helpers for the FastAPI backend."""

from __future__ import annotations

import logging
import json
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.manager import ManagerActivityLog

logger = logging.getLogger(__name__)


_VALID_CATEGORIES = {
    "auth",
    "server",
    "user",
    "host_node",
    "automation",
    "settings",
    "certificate",
    "email",
    "tunnel",
    "other",
}

_STATUS_MAP = {
    "success": "success",
    "ok": "success",
    "failure": "failed",
    "fail": "failed",
    "error": "failed",
    "failed": "failed",
    "partial": "partial",
    "warning": "partial",
    "info": "info",
}


def _normalize_status(status: str) -> str:
    return _STATUS_MAP.get(status, "info")


def _normalize_category(category: str) -> str:
    c = (category or "").strip().lower()
    return c if c in _VALID_CATEGORIES else "other"


async def log_manager_activity(
    db: AsyncSession,
    *,
    actor: str,
    category: str,
    status: str,
    detail_key: str,
    detail_params: Mapping[str, Any] | None = None,
) -> None:
    try:
        status_normalized = _normalize_status(status)
        category_normalized = _normalize_category(category)
        db.add(
            ManagerActivityLog(
                actor=actor[:100],
                category=category_normalized[:32],
                status=status_normalized[:50],
                detail_key=detail_key[:120],
                detail_params=json.dumps(dict(detail_params or {}), ensure_ascii=False, default=str),
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Failed to write manager activity log")
