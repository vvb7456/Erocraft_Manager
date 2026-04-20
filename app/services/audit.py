"""Audit logging helpers for the FastAPI backend."""

from __future__ import annotations

import logging
import json
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.manager import ManagerActivityLog

logger = logging.getLogger(__name__)


async def log_manager_activity(
    db: AsyncSession,
    *,
    actor: str,
    action: str,
    status: str,
    detail_key: str,
    detail_params: Mapping[str, Any] | None = None,
) -> None:
    try:
        db.add(
            ManagerActivityLog(
                actor=actor[:100],
                action=action[:100],
                status=status[:50],
                detail_key=detail_key[:120],
                detail_params=json.dumps(dict(detail_params or {}), ensure_ascii=False, default=str),
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Failed to write manager activity log")
