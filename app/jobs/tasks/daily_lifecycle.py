"""Daily lifecycle batch — serial orchestration of all daily automation tasks.

Runs suspend → delete → trial_expire → llm_sync in that order, each in its
own DB session. Failures in any stage are logged but do not block subsequent
stages. Registered as a single unconditional cron job (not gated by
AUTOMATION_SUSPEND_ENABLED / AUTOMATION_DELETE_ENABLED — those toggles are
read at execution time by the respective stage).
"""

from __future__ import annotations

import logging
from typing import Mapping

from apscheduler.schedulers.base import BaseScheduler

from app.db.session import get_session_factory
from app.jobs.tasks.common import get_job_today
from app.services.audit import log_manager_activity

logger = logging.getLogger(__name__)

DAILY_LIFECYCLE_JOB_ID = "daily_lifecycle_batch"


def sync_daily_lifecycle_job(
    scheduler: BaseScheduler, settings: Mapping[str, object]
) -> None:
    """Register the single daily batch cron job.

    Unlike the old per-task sync_*_job functions, this is always registered —
    the individual stage toggles (AUTOMATION_SUSPEND_ENABLED etc.) are
    honoured at execution time, not at registration time.
    """
    scheduler.add_job(
        run_daily_lifecycle_batch,
        id=DAILY_LIFECYCLE_JOB_ID,
        trigger="cron",
        hour=int(settings["AUTOMATION_RUN_HOUR"]),
        minute=int(settings["AUTOMATION_RUN_MINUTE"]),
        timezone=str(settings["TIMEZONE"]),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )


async def run_daily_lifecycle_batch() -> None:
    """Run all daily automation stages in serial order.

    Order rationale: suspend must complete before delete (suspended servers
    are the input set for delete's grace-period check); trial_expire deletes
    trial servers with zero grace; llm_sync aligns key states after all
    server lifecycle changes have settled.
    """
    session_factory = get_session_factory()

    async with session_factory() as db:
        await log_manager_activity(
            db,
            actor="system",
            category="automation",
            status="info",
            detail_key="automated_daily_lifecycle_started",
        )

    # ── Stage 1: suspend expired servers (if enabled) ──
    try:
        from app.jobs.tasks.suspend import run_suspend_task
        await run_suspend_task()
    except Exception:
        logger.warning("daily lifecycle: suspend stage failed", exc_info=True)

    # ── Stage 2: delete long-expired servers (if enabled) ──
    try:
        from app.jobs.tasks.delete import run_delete_task
        await run_delete_task()
    except Exception:
        logger.warning("daily lifecycle: delete stage failed", exc_info=True)

    # ── Stage 3: expire trial servers (always runs) ──
    try:
        from app.jobs.tasks.trial_expire import run_trial_expire_task
        await run_trial_expire_task()
    except Exception:
        logger.warning("daily lifecycle: trial_expire stage failed", exc_info=True)

    # ── Stage 4: LLM daily sync (always runs) ──
    # Runs after all server lifecycle changes so key states align with
    # the final server state (suspended / deleted / trial-deleted).
    try:
        from app.services.llm_provision import sync as llm_sync
        async with session_factory() as llm_db:
            await llm_sync.run_llm_daily_sync(llm_db)
    except Exception:
        logger.warning("daily lifecycle: LLM sync stage failed", exc_info=True)

    async with session_factory() as db:
        await log_manager_activity(
            db,
            actor="system",
            category="automation",
            status="info",
            detail_key="automated_daily_lifecycle_finished",
        )
