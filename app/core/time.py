"""Time helpers for runtime settings and business rules."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def local_today(timezone_name: str) -> date:
    try:
        timezone = ZoneInfo(timezone_name)
    except Exception:
        timezone = ZoneInfo("UTC")
    return datetime.now(timezone).date()


async def get_runtime_timezone(db: AsyncSession) -> str:
    from app.core.runtime_settings import AUTOMATION_SPECS
    from app.core.settings_store import get_settings_store

    tz_name = await get_settings_store().get(
        db, "TIMEZONE", AUTOMATION_SPECS["TIMEZONE"].default_value()
    )
    return str(tz_name)


def format_in_timezone(dt: datetime | None, timezone_name: str) -> str | None:
    if dt is None:
        return None
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo("UTC")
    aware = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
    local_dt = aware.astimezone(tz)
    offset = local_dt.utcoffset()
    total_seconds = int(offset.total_seconds()) if offset is not None else 0
    sign = "+" if total_seconds >= 0 else "-"
    hours, rem = divmod(abs(total_seconds), 3600)
    minutes = rem // 60
    return f"{local_dt.strftime('%Y-%m-%d %H:%M:%S')} (UTC{sign}{hours:02d}:{minutes:02d})"


def utc_naive_now() -> datetime:
    """Project-wide convention for "now, in UTC, without tzinfo".

    MySQL ``DATETIME`` columns are naive, and SQLAlchemy's default binding
    refuses tz-aware values against them. Several modules therefore wrote
    ``datetime.now(UTC).replace(tzinfo=None)`` inline. Centralising it here
    avoids drift (CR §5.6 / §6.1) and gives a single place to change if we
    ever migrate to ``DateTime(timezone=True)``.

    Returns a naive ``datetime`` whose value is UTC wall-clock.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def to_iso_z(dt: datetime | None) -> str | None:
    """Serialize a (possibly naive-UTC) datetime as ``...Z``.

    Use this in API responses so the frontend never has to guess whether a
    bare ``isoformat()`` string is UTC or local. Aware datetimes in a
    non-UTC zone are converted to UTC first.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.astimezone(UTC).replace(tzinfo=None).isoformat() + "Z"
