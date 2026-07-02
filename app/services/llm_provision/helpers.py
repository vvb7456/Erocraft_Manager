"""Shared helpers for LLM quota serialization."""

from __future__ import annotations

from app.core.time import utc_naive_now
from app.db.models.manager import ServerLlmKey


def next_reset_date(row: ServerLlmKey) -> str:
    """Compute the next monthly quota reset date as ``YYYY-MM-DD``.

    Reset happens on ``row.reset_day`` each month. If this month's reset has
    already run (``last_reset_at`` is in the current month), the next reset is
    next month's ``reset_day``; otherwise it's this month's (or today, if the
    day has already passed but no reset was recorded).
    """
    now = utc_naive_now()
    last_reset = row.last_reset_at
    reset_day = row.reset_day

    if last_reset and last_reset.year == now.year and last_reset.month == now.month:
        if now.month == 12:
            return f"{now.year + 1}-01-{reset_day:02d}"
        return f"{now.year}-{now.month + 1:02d}-{reset_day:02d}"
    if now.day < reset_day:
        return f"{now.year}-{now.month:02d}-{reset_day:02d}"
    return now.strftime("%Y-%m-%d")
