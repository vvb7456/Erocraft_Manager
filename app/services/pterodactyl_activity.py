"""Pterodactyl-compatible activity log writer.

The records written here intentionally match Pterodactyl Panel's native
`activity_logs` and `activity_log_subjects` contract so that the upstream Panel
can render them without custom code.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Iterable

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import extract_client_ip
from app.db.models.pterodactyl import ActivityLog, ActivityLogSubject, PteroServer, PteroUser

PTERODACTYL_DISABLED_ACTIVITY_EVENTS = frozenset({"server:file.upload"})

SUBJECT_ALLOCATION = "allocation"
SUBJECT_API_KEY = "api_key"
SUBJECT_BACKUP = "backup"
SUBJECT_DATABASE = "database"
SUBJECT_EGG = "egg"
SUBJECT_EGG_VARIABLE = "egg_variable"
SUBJECT_SCHEDULE = "schedule"
SUBJECT_SERVER = "server"
SUBJECT_SSH_KEY = "ssh_key"
SUBJECT_TASK = "task"
SUBJECT_USER = "user"


def get_request_ip(request: Request | None) -> str:
    """Return a trusted Panel-compatible client IP string."""
    return extract_client_ip(request, fallback="127.0.0.1")


def decode_activity_properties(raw: str | None) -> dict[str, Any] | list[Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, (dict, list)) else {}


class PterodactylActivityLogger:
    async def _log_activity(
        self,
        db: AsyncSession,
        *,
        primary_subject: tuple[str, int],
        actor: PteroUser | None,
        event: str,
        properties: dict[str, Any] | list[Any] | None = None,
        request: Request | None = None,
        subjects: Iterable[tuple[str, int]] = (),
        batch: str | None = None,
        description: str | None = None,
        api_key_id: int | None = None,
        timestamp: datetime | None = None,
    ) -> ActivityLog:
        ts = timestamp or datetime.now(UTC)
        if ts.tzinfo is not None:
            ts = ts.astimezone(UTC).replace(tzinfo=None)
        activity = ActivityLog(
            batch=batch,
            event=event,
            ip=get_request_ip(request),
            description=description,
            actor_type=SUBJECT_USER if actor is not None else None,
            actor_id=actor.id if actor is not None else None,
            api_key_id=api_key_id,
            properties=json.dumps(properties if properties is not None else {}, ensure_ascii=False, separators=(",", ":")),
            timestamp=ts,
        )
        db.add(activity)
        await db.flush()

        subject_rows: list[ActivityLogSubject] = []
        seen: set[tuple[str, int]] = set()
        for subject_type, subject_id in (primary_subject, *tuple(subjects)):
            key = (subject_type, int(subject_id))
            if key in seen:
                continue
            seen.add(key)
            subject_rows.append(
                ActivityLogSubject(
                    activity_log_id=activity.id,
                    subject_type=subject_type,
                    subject_id=int(subject_id),
                )
            )

        db.add_all(subject_rows)
        return activity

    async def log_server_activity(
        self,
        db: AsyncSession,
        *,
        server: PteroServer,
        actor: PteroUser | None,
        event: str,
        properties: dict[str, Any] | list[Any] | None = None,
        request: Request | None = None,
        subjects: Iterable[tuple[str, int]] = (),
        batch: str | None = None,
        description: str | None = None,
        api_key_id: int | None = None,
        timestamp: datetime | None = None,
    ) -> ActivityLog:
        """Add one native server activity entry to the current transaction."""

        if not event.startswith("server:"):
            raise ValueError("Server activity events must use the 'server:' namespace")

        return await self._log_activity(
            db,
            primary_subject=(SUBJECT_SERVER, server.id),
            actor=actor,
            event=event,
            properties=properties,
            request=request,
            subjects=subjects,
            batch=batch,
            description=description,
            api_key_id=api_key_id,
            timestamp=timestamp,
        )

    async def log_account_activity(
        self,
        db: AsyncSession,
        *,
        user: PteroUser,
        event: str,
        actor: PteroUser | None = None,
        properties: dict[str, Any] | list[Any] | None = None,
        request: Request | None = None,
        batch: str | None = None,
        description: str | None = None,
        api_key_id: int | None = None,
        timestamp: datetime | None = None,
    ) -> ActivityLog:
        """Add one native account activity entry to the current transaction."""

        if not event.startswith(("auth:", "event:", "user:")):
            raise ValueError("Account activity events must use the 'auth:', 'event:', or 'user:' namespace")

        return await self._log_activity(
            db,
            primary_subject=(SUBJECT_USER, user.id),
            actor=actor,
            event=event,
            properties=properties,
            request=request,
            batch=batch,
            description=description,
            api_key_id=api_key_id,
            timestamp=timestamp,
        )


pterodactyl_activity_logger = PterodactylActivityLogger()
