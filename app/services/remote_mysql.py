"""Panel-compatible database (MySQL) management.

Mirrors Pterodactyl's ``DatabaseManagementService::delete``: connect to the
remote MySQL host recorded in ``database_hosts``, ``DROP DATABASE`` and
``DROP USER``, then delete the panel ``databases`` row.

The remote host's password is stored Laravel-encrypted with the panel
``APP_KEY``; we reuse :meth:`WingsService._decrypt_laravel` for that.

This module does NOT itself commit — the caller (``panel_db.delete_server_row``)
must commit after calling :func:`drop_server_databases`.
"""

from __future__ import annotations

import logging

import aiomysql
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pterodactyl import PteroDatabase, PteroDatabaseHost
from app.services.wings import wings_service

logger = logging.getLogger(__name__)


class PanelDatabaseError(RuntimeError):
    """Raised when a panel-compatible database operation fails."""


def _quote_ident(name: str) -> str:
    """Quote an identifier with backticks, escaping any embedded backticks.

    Used for DATABASE/USER names. Pterodactyl always generates names from the
    pattern ``s{server_id}_*`` / ``u{server_id}_*`` so this only acts as a
    defence-in-depth measure.
    """
    return "`" + name.replace("`", "``") + "`"


async def _connect_remote(host: PteroDatabaseHost) -> aiomysql.Connection:
    """Open a connection to the remote MySQL host using its decrypted creds."""
    try:
        password = wings_service._decrypt_laravel(host.password)  # noqa: SLF001
    except Exception as exc:  # pragma: no cover - decrypt errors caught upstream
        raise PanelDatabaseError(
            f"无法解密 database_host {host.id} 的密码: {exc}"
        ) from exc

    try:
        return await aiomysql.connect(
            host=host.host,
            port=int(host.port),
            user=host.username,
            password=password,
            autocommit=True,
            connect_timeout=10,
        )
    except Exception as exc:
        raise PanelDatabaseError(
            f"连接 database_host {host.id} ({host.host}:{host.port}) 失败: {exc}"
        ) from exc


async def _drop_database_and_user(
    host: PteroDatabaseHost,
    database_name: str,
    username: str,
    remote: str,
) -> None:
    """DROP the database and the user/grant on the remote MySQL host."""
    conn = await _connect_remote(host)
    try:
        async with conn.cursor() as cur:
            await cur.execute(f"DROP DATABASE IF EXISTS {_quote_ident(database_name)}")
            await cur.execute(
                f"DROP USER IF EXISTS {_quote_ident(username)}@{_quote_ident(remote)}"
            )
            await cur.execute("FLUSH PRIVILEGES")
    finally:
        conn.close()


async def drop_server_databases(db: AsyncSession, server_id: int) -> tuple[int, list[str]]:
    """For every ``databases`` row owned by this server: drop the remote DB
    and the remote user, then delete the panel row.

    **Best-effort semantics**: this runs *after* Wings has already destroyed
    the server's container/volume, so giving up half-way would leave the user
    looking at a "ghost" server that can never be started. Instead we attempt
    every entry independently — successful ones get their panel ``databases``
    row removed; failed ones stay in the panel DB so an operator can audit /
    finish them manually, but the lifecycle continues.

    Returns ``(removed, errors)`` where ``errors`` is a list of human-readable
    strings describing each failed drop (empty on full success). The caller
    decides whether to surface the errors as a warning while still deleting
    the panel ``servers`` row.

    Caller is responsible for committing the SQLAlchemy session.
    """
    rows = await db.execute(
        select(PteroDatabase).where(PteroDatabase.server_id == server_id)
    )
    databases = list(rows.scalars().all())
    if not databases:
        return 0, []

    # Group by host so we open one connection per host
    hosts_by_id: dict[int, PteroDatabaseHost] = {}
    for entry in databases:
        if entry.database_host_id not in hosts_by_id:
            host = await db.get(PteroDatabaseHost, entry.database_host_id)
            if host is None:
                # Missing host row → we can't possibly drop, but we also can't
                # keep the orphan panel row around forever. Drop the panel row
                # and report the orphan.
                await db.execute(
                    sql_delete(PteroDatabase).where(PteroDatabase.id == entry.id)
                )
                continue
            hosts_by_id[entry.database_host_id] = host

    removed = 0
    errors: list[str] = []
    for entry in databases:
        host = hosts_by_id.get(entry.database_host_id)
        if host is None:
            # already handled above (orphan host)
            continue
        try:
            await _drop_database_and_user(
                host,
                entry.database,
                entry.username,
                entry.remote,
            )
        except PanelDatabaseError as exc:
            msg = (
                f"远端 DROP 失败 db={entry.database} user={entry.username}@{entry.remote} "
                f"host={host.host}:{host.port} ({exc})"
            )
            logger.error("server=%s %s", server_id, msg)
            errors.append(msg)
            # Leave the panel ``databases`` row in place so an admin can see
            # what's leftover and finish it manually.
            continue
        await db.execute(
            sql_delete(PteroDatabase).where(PteroDatabase.id == entry.id)
        )
        removed += 1

    return removed, errors
