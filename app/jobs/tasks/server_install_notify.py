"""Send a one-shot "server installed" email when a server's first install
finishes.

Mechanism
---------
Wings does not call back to the manager when an install finishes, so this
job polls ``servers.installed_at`` paired with our own
``manager_server_meta.install_notified_at`` flag:

* A server is **eligible** when ``installed_at`` is set, the row's
  ``status`` is NULL (i.e. not ``installing`` / ``suspended`` /
  ``install_failed``), ``install_notified_at`` is NULL, and the retry
  backoff window has elapsed (``install_notify_next_at`` is NULL or in
  the past).
* On send success we set ``install_notified_at = NOW()`` so subsequent
  scans skip the row.
* On send failure we bump ``install_notify_attempts`` and schedule the
  next retry via ``install_notify_next_at`` on an exponential backoff
  (``_RETRY_DELAYS`` — 1m, 5m, 15m, 1h, 4h, mirroring the billing apply
  engine). Once the budget is exhausted we set ``install_notified_at`` to
  give up, so a permanently-undeliverable recipient does not spam the
  audit log every tick. The deterministic "owner has no email" case sets
  the flag immediately.

Reinstalls (admin / user-triggered) clear ``installed_at`` but do **not**
clear ``install_notified_at`` (only this job and the baseline backfill
write it). After a reinstall finishes, ``install_notified_at`` is still
set from the original install → no email goes out. That's the intended
"first install only" semantics.

This job's frequency is decoupled from the monitoring loop: it runs every
minute (cheap query) and is bypassable when SMTP / automation_email is
disabled.
"""

from __future__ import annotations

import logging
from typing import Mapping

from apscheduler.schedulers.base import BaseScheduler
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime_settings import SETTINGS_SPECS
from app.core.settings_store import get_settings_store
from app.db.session import get_session_factory
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

INSTALL_NOTIFY_JOB_ID = "server_install_notify"

# Exponential backoff schedule for failed install-notify sends, mirroring
# the billing apply engine (apply_engine.RETRY_DELAYS). After each failure
# the row is skipped until ``install_notify_next_at``; once attempts exceed
# the schedule length the row is finalized as given-up so the audit log is
# not spammed by a permanently-undeliverable recipient (e.g. an invalid
# address the relay rejects with a 5xx such as QQ's ``559 invaddr``).
# 1m, 5m, 15m, 1h, 4h
_RETRY_DELAYS = [60, 5 * 60, 15 * 60, 60 * 60, 4 * 60 * 60]


def sync_install_notify_job(scheduler: BaseScheduler, settings: Mapping[str, object]) -> None:
    """Wire up the job to APScheduler. Driven by ``AUTOMATION_EMAIL_ENABLED``."""
    if settings.get("AUTOMATION_EMAIL_ENABLED"):
        scheduler.add_job(
            run_install_notify_scan,
            id=INSTALL_NOTIFY_JOB_ID,
            trigger="interval",
            minutes=1,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=120,
        )
        return

    if scheduler.get_job(INSTALL_NOTIFY_JOB_ID):
        scheduler.remove_job(INSTALL_NOTIFY_JOB_ID)


_SCAN_SQL = text(
    """
    SELECT
        s.id           AS server_id,
        s.uuid         AS server_uuid,
        s.name         AS server_name,
        s.installed_at AS installed_at,
        u.id           AS owner_id,
        u.username     AS username,
        u.email        AS email,
        COALESCE(m.install_notify_attempts, 0) AS notify_attempts
    FROM servers s
    LEFT JOIN manager_server_meta m ON m.server_id = s.id
    JOIN users u ON u.id = s.owner_id
    WHERE s.installed_at IS NOT NULL
      AND s.status IS NULL
      AND (m.install_notified_at IS NULL)
      AND (
          m.install_notify_next_at IS NULL
          OR m.install_notify_next_at <= NOW()
      )
    ORDER BY s.installed_at ASC
    LIMIT 100
    """
)


async def _mark_notified(db: AsyncSession, server_id: int) -> None:
    """Upsert manager_server_meta.install_notified_at = NOW().

    Uses INSERT ... ON DUPLICATE KEY UPDATE so a server with no meta row
    yet (e.g. created outside the billing flow) still gets marked.
    """
    await db.execute(
        text(
            """
            INSERT INTO manager_server_meta (server_id, install_notified_at)
            VALUES (:sid, NOW())
            ON DUPLICATE KEY UPDATE install_notified_at = NOW()
            """
        ).bindparams(sid=server_id)
    )
    await db.commit()


async def _record_notify_failure(
    db: AsyncSession, server_id: int, attempts_before: int
) -> bool:
    """Bump ``install_notify_attempts`` and schedule the next retry.

    Mirrors apply_engine's ``_record_failure_and_release``: increment the
    counter, and if it still fits within ``_RETRY_DELAYS`` set
    ``install_notify_next_at = NOW() + _RETRY_DELAYS[attempts-1]``; once
    the budget is exhausted set ``install_notified_at`` to give up and
    stop the row being scanned. Returns True iff the budget was exhausted.
    """
    new_attempts = attempts_before + 1
    exhausted = new_attempts > len(_RETRY_DELAYS)
    if exhausted:
        await db.execute(
            text(
                """
                INSERT INTO manager_server_meta (server_id, install_notify_attempts)
                VALUES (:sid, :att)
                ON DUPLICATE KEY UPDATE
                    install_notify_attempts = :att,
                    install_notify_next_at = NULL,
                    install_notified_at = NOW()
                """
            ).bindparams(sid=server_id, att=new_attempts)
        )
    else:
        delay = _RETRY_DELAYS[new_attempts - 1]
        await db.execute(
            text(
                """
                INSERT INTO manager_server_meta
                    (server_id, install_notify_attempts, install_notify_next_at)
                VALUES (:sid, :att, DATE_ADD(NOW(), INTERVAL :delay SECOND))
                ON DUPLICATE KEY UPDATE
                    install_notify_attempts = :att,
                    install_notify_next_at = DATE_ADD(NOW(), INTERVAL :delay SECOND)
                """
            ).bindparams(sid=server_id, att=new_attempts, delay=delay)
        )
    await db.commit()
    return exhausted


async def run_install_notify_scan() -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        rows = (await db.execute(_SCAN_SQL)).mappings().all()
        if not rows:
            return

        brand_name = await get_settings_store().get(
            db, "BRAND_NAME", SETTINGS_SPECS["BRAND_NAME"].default_value(),
        )
        site_url = await get_site_url(db)
        cfg = await get_smtp_config(db)
        template = await load_template(db, "server_installed")
        delay = await get_email_delay(db)

        sent_count = 0
        skipped_count = 0
        async with EmailClient(
            cfg, site_url, db=db, actor="system",
            log_category="automation",
            audit_source="server_install_notify",
        ) as client:
            for index, row in enumerate(rows):
                server_id = int(row["server_id"])
                email = (row["email"] or "").strip()
                username = row["username"] or ""

                # No email on file: mark notified anyway so we don't keep
                # picking this row up forever. Surface as audit warning.
                if not email:
                    await log_manager_activity(
                        db,
                        actor="system",
                        category="automation",
                        status="warning",
                        detail_key="install_notify.no_email",
                        detail_params={
                            "server_id": server_id,
                            "owner_id": int(row["owner_id"]),
                        },
                    )
                    await _mark_notified(db, server_id)
                    skipped_count += 1
                    continue

                installed_at = row["installed_at"]
                installed_str = (
                    installed_at.strftime("%Y-%m-%d %H:%M:%S")
                    if installed_at is not None
                    else ""
                )

                subject, body = render_template_body(
                    template,
                    {
                        "brand_name": brand_name,
                        "username": username,
                        "server_name": row["server_name"] or "",
                        "server_id": server_id,
                        "server_uuid": row["server_uuid"] or "",
                        "installed_at": installed_str,
                    },
                )
                action_text = "进入控制台" if site_url else None
                action_url = (
                    f"{site_url}/#/servers/{server_id}/console"
                    if site_url else None
                )
                sent, err = await client.send(
                    recipient_email=email,
                    subject=subject,
                    main_content_raw=body,
                    greeting=f"您好, {username}!" if username else "您好!",
                    action_text=action_text,
                    action_url=action_url,
                )
                if sent:
                    await _mark_notified(db, server_id)
                    sent_count += 1
                else:
                    # Back off: schedule the next retry on an exponential
                    # delay (see _RETRY_DELAYS) so a permanently-failing
                    # recipient does not spam the audit log every tick.
                    # Once the budget is exhausted the row is finalized.
                    attempts_before = int(row["notify_attempts"] or 0)
                    exhausted = await _record_notify_failure(
                        db, server_id, attempts_before
                    )
                    logger.warning(
                        "install_notify: send failed for server %s "
                        "(attempt %d%s): %s",
                        server_id,
                        attempts_before + 1,
                        ", retries exhausted — giving up" if exhausted else "",
                        err,
                    )

                if delay > 0 and index < len(rows) - 1:
                    import asyncio
                    await asyncio.sleep(delay)

        if sent_count or skipped_count:
            await log_manager_activity(
                db,
                actor="system",
                category="automation",
                status="success" if sent_count else "info",
                detail_key="install_notify.run",
                detail_params={
                    "sent": sent_count,
                    "skipped": skipped_count,
                    "scanned": len(rows),
                },
            )

