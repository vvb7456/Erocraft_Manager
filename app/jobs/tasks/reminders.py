"""Automated reminder emails for expiring and pending-delete servers."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Mapping

from apscheduler.schedulers.base import BaseScheduler

from app.core.runtime_settings import SETTINGS_SPECS
from app.core.settings_store import get_settings_store
from app.db.models.pterodactyl import PteroServer
from app.db.repositories.servers import server_repository
from app.db.session import get_session_factory
from app.jobs.tasks.common import get_job_today
from app.services.audit import log_manager_activity
from app.services.email import (
    EmailClient,
    get_email_delay,
    get_site_url,
    get_smtp_config,
    load_template,
    render_template_body,
)

logger = logging.getLogger(__name__)

EXPIRY_REMINDER_JOB_ID = "auto_expiry_reminder_task"
PRE_DELETE_REMINDER_JOB_ID = "auto_pre_delete_reminder_task"


def sync_reminder_jobs(scheduler: BaseScheduler, settings: Mapping[str, object]) -> None:
    if settings.get("AUTOMATION_EMAIL_ENABLED"):
        scheduler.add_job(
            run_reminder_task,
            id=EXPIRY_REMINDER_JOB_ID,
            trigger="cron",
            hour=int(settings["AUTOMATION_EMAIL_RUN_HOUR"]),
            minute=int(settings["AUTOMATION_EMAIL_RUN_MINUTE"]),
            timezone=str(settings["TIMEZONE"]),
            args=("expiry",),
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=300,
        )
        scheduler.add_job(
            run_reminder_task,
            id=PRE_DELETE_REMINDER_JOB_ID,
            trigger="cron",
            hour=int(settings["AUTOMATION_EMAIL_RUN_HOUR"]),
            minute=int(settings["AUTOMATION_EMAIL_RUN_MINUTE"]),
            timezone=str(settings["TIMEZONE"]),
            args=("pre_delete",),
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=300,
        )
        return

    for job_id in (EXPIRY_REMINDER_JOB_ID, PRE_DELETE_REMINDER_JOB_ID):
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)


async def run_reminder_task(reminder_type: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        if reminder_type == "expiry":
            task_name = "automated_expiry_reminder"
            target_date = await get_job_today(db) + timedelta(days=1)
            template = await load_template(db, "reminder")
        elif reminder_type == "pre_delete":
            task_name = "automated_pre_delete_reminder"
            delete_days = int(await get_settings_store().get(db, "AUTOMATION_DELETE_DAYS", 14))
            target_date = await get_job_today(db) - timedelta(days=delete_days - 1)
            template = await load_template(db, "pre_delete")
        else:
            logger.error("Unknown reminder type: %s", reminder_type)
            return

        await log_manager_activity(
            db,
            actor="system",
            category="automation",
            status="info",
            detail_key="automated_reminder_started",
            detail_params={"type": reminder_type},
        )

        try:
            servers = await server_repository.list_expiring_on(db, target_date)
            if not servers:
                await log_manager_activity(
                    db,
                    actor="system",
                    category="automation",
                    status="info",
                    detail_key="automated_reminder_noop",
                    detail_params={"type": reminder_type},
                )
                return

            brand_name = await get_settings_store().get(
                db,
                "BRAND_NAME",
                SETTINGS_SPECS["BRAND_NAME"].default_value(),
            )
            action_url = await get_site_url(db) or None
            action_text = "登录系统处理" if action_url else None
            delay = await get_email_delay(db)

            # One SMTP connection for the whole batch — reused across
            # every owner so we avoid the connect/login round-trip per
            # message and stay well under most providers' rate limits.
            cfg = await get_smtp_config(db)
            site_url = await get_site_url(db)
            async with EmailClient(
                cfg, site_url, db=db, actor="system",
                log_category="automation",
                audit_source=f"{reminder_type}_reminder",
            ) as client:
                if reminder_type == "expiry":
                    sent_count = await _send_expiry_reminders(
                        client,
                        servers,
                        template=template,
                        brand_name=str(brand_name),
                        action_text=action_text,
                        action_url=action_url,
                        delay=delay,
                        target_date=target_date,
                    )
                else:
                    sent_count = await _send_pre_delete_reminders(
                        client,
                        db,
                        servers,
                        template=template,
                        brand_name=str(brand_name),
                        action_text=action_text,
                        action_url=action_url,
                        delay=delay,
                    )

            await log_manager_activity(
                db,
                actor="system",
                category="automation",
                status="success",
                detail_key="automated_reminder_finished",
                detail_params={"type": reminder_type, "sent": sent_count},
            )
        except Exception as exc:
            logger.exception("Automated reminder task failed: %s", reminder_type)
            await log_manager_activity(
                db,
                actor="system",
                category="automation",
                status="failure",
                detail_key="automated_reminder_failed",
                detail_params={"type": reminder_type, "error": str(exc)},
            )


async def _send_expiry_reminders(
    client: EmailClient,
    servers: list[PteroServer],
    *,
    template,
    brand_name: str,
    action_text: str | None,
    action_url: str | None,
    delay: int,
    target_date,
) -> int:
    grouped: dict[int, list[PteroServer]] = {}
    for server in servers:
        grouped.setdefault(server.owner_id, []).append(server)

    sent_count = 0
    owner_groups = list(grouped.values())
    for index, owner_servers in enumerate(owner_groups):
        owner = owner_servers[0].owner
        if owner is None or not owner.email:
            continue

        server_list = "\n".join(f"- {server.name} (ID: {server.id})" for server in owner_servers)
        subject, body = render_template_body(
            template,
            {
                "brand_name": brand_name,
                "username": owner.username,
                "expiration_date": target_date.strftime("%Y-%m-%d"),
                "server_count": len(owner_servers),
                "server_list": server_list,
            },
        )
        sent, _ = await client.send(
            recipient_email=owner.email,
            subject=subject,
            main_content_raw=body,
            greeting=f"您好, {owner.username}!",
            action_text=action_text,
            action_url=action_url,
        )
        if sent:
            sent_count += 1
        if delay > 0 and index < len(owner_groups) - 1:
            await asyncio.sleep(delay)

    return sent_count


async def _send_pre_delete_reminders(
    client: EmailClient,
    db,
    servers: list[PteroServer],
    *,
    template,
    brand_name: str,
    action_text: str | None,
    action_url: str | None,
    delay: int,
) -> int:
    sent_count = 0
    today = await get_job_today(db)
    deletion_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    for index, server in enumerate(servers):
        owner = server.owner
        if owner is None or not owner.email:
            continue

        subject, body = render_template_body(
            template,
            {
                "brand_name": brand_name,
                "username": owner.username,
                "server_name": server.name,
                "server_id": server.id,
                "deletion_date": deletion_date,
            },
        )
        sent, _ = await client.send(
            recipient_email=owner.email,
            subject=subject,
            main_content_raw=body,
            greeting=f"您好, {owner.username}!",
            action_text=action_text,
            action_url=action_url,
        )
        if sent:
            sent_count += 1
        if delay > 0 and index < len(servers) - 1:
            await asyncio.sleep(delay)

    return sent_count
