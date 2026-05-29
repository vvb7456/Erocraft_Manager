"""Logging helpers for the FastAPI backend."""

from __future__ import annotations

import logging


# Loggers we explicitly silence to remove non-auditable noise from log files.
# Nginx already records every HTTP request, and APScheduler emits two lines
# per scheduled tick (Running … / executed successfully) that drown out
# anything actionable. Keep ERROR/WARNING so failures still surface.
_NOISY_LOGGERS: tuple[str, ...] = (
    "uvicorn.access",
    "apscheduler.executors.default",
    "apscheduler.scheduler",
)


def _silence_noisy_loggers() -> None:
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def configure_logging(level: str = "INFO") -> None:
    root_logger = logging.getLogger()
    if root_logger.handlers:
        root_logger.setLevel(level.upper())
        _silence_noisy_loggers()
        return

    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    _silence_noisy_loggers()
