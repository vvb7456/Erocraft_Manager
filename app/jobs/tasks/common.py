"""Shared helpers for manager-jobs task execution."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime_settings import AUTOMATION_SPECS
from app.core.settings_store import get_settings_store
from app.core.time import local_today


async def get_job_today(db: AsyncSession) -> date:
    timezone_name = await get_settings_store().get(
        db,
        "TIMEZONE",
        AUTOMATION_SPECS["TIMEZONE"].default_value(),
    )
    return local_today(str(timezone_name))