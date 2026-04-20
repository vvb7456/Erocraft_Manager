"""Time helpers for runtime settings and business rules."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def local_today(timezone_name: str) -> datetime.date:
    try:
        timezone = ZoneInfo(timezone_name)
    except Exception:
        timezone = ZoneInfo("UTC")
    return datetime.now(timezone).date()
