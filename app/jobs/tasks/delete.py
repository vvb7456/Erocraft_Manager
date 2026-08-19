"""Automated delete task for long-expired servers."""

from __future__ import annotations

import logging
from datetime import timedelta

from app.core.settings_store import get_settings_store
from app.db.repositories.servers import server_repository
from app.db.session import get_session_factory
from app.jobs.tasks.common import get_job_today
from app.services.audit import log_manager_activity
from app.services import server_lifecycle
from app.services.server_lifecycle import LifecycleError

logger = logging.getLogger(__name__)


async def run_delete_task() -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        await log_manager_activity(
            db,
            actor="system",
            category="automation",
            status="info",
            detail_key="automated_delete_started",
        )

        try:
            delete_days = await get_settings_store().get(db, "AUTOMATION_DELETE_DAYS", 14)
            threshold = await get_job_today(db) - timedelta(days=int(delete_days))
            servers = await server_repository.list_expired_before_or_on(db, threshold)
            if not servers:
                await log_manager_activity(
                    db,
                    actor="system",
                    category="automation",
                    status="info",
                    detail_key="automated_delete_noop",
                )
                return

            success_count = 0
            failed_ids: list[int] = []
            for server in servers:
                try:
                    await server_lifecycle.delete_server(db, server.id)
                    success_count += 1
                except LifecycleError:
                    await db.rollback()
                    failed_ids.append(server.id)
                    logger.exception("Failed to delete server %s in automated task", server.id)

            await log_manager_activity(
                db,
                actor="system",
                category="automation",
                status="success" if success_count or not failed_ids else "failure",
                detail_key="automated_delete_finished",
                detail_params={"success": success_count, "failed": len(failed_ids), "failed_ids": ", ".join(str(server_id) for server_id in failed_ids)},
            )
        except Exception as exc:
            logger.exception("Automated delete task failed")
            await log_manager_activity(
                db,
                actor="system",
                category="automation",
                status="failure",
                detail_key="automated_delete_failed",
                detail_params={"error": str(exc)},
            )
