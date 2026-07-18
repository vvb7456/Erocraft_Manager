"""Time helpers for runtime settings and business rules."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


def local_today(timezone_name: str) -> date:
    try:
        timezone = ZoneInfo(timezone_name)
    except Exception:
        timezone = ZoneInfo("UTC")
    return datetime.now(timezone).date()


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
