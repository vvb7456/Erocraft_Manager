"""Entrypoint for the standalone jobs process."""

from __future__ import annotations

import asyncio
import logging

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import dispose_engine
from app.jobs.scheduler import build_scheduler, sync_managed_jobs

logger = logging.getLogger(__name__)


async def run_jobs_process() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    scheduler = build_scheduler()
    await sync_managed_jobs(scheduler)
    scheduler.start()
    logger.info("manager-jobs process started")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        scheduler.shutdown(wait=False)
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(run_jobs_process())
