"""Server lifecycle orchestration — combines panel_db writes with Wings calls.

This is the **only** module routers/jobs should import for server CRUD and
state transitions. It guarantees the panel DB and Wings stay consistent.

See docs/PTERO_API_DECOUPLING.md for the architecture.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import panel_db
from app.services.audit import log_manager_activity
from app.services.panel_db import (
    CreatedServer,
    CreatedUser,
    PanelDBError,
    PanelDBValidationError,
)
from app.services.remote_mysql import PanelDatabaseError, drop_server_databases
from app.services.wings import WingsServiceError, wings_service

logger = logging.getLogger(__name__)


class LifecycleError(RuntimeError):
    """Raised when a lifecycle step fails. Wraps panel-DB and Wings errors."""


class LifecycleValidationError(LifecycleError):
    """Raised when a lifecycle step fails because of caller-provided input.

    Routers should map this to HTTP 422 (Unprocessable Entity) so frontends
    can surface field-level validation errors. Generic ``LifecycleError``
    still maps to 502 (true upstream / server failures).
    """


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    email: str,
    first_name: str,
    last_name: str,
    password: str,
    root_admin: bool = False,
) -> CreatedUser:
    try:
        return await panel_db.create_user(
            db,
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=password,
            root_admin=root_admin,
        )
    except PanelDBError as exc:
        raise LifecycleError(str(exc)) from exc


async def update_user(
    db: AsyncSession,
    user_id: int,
    *,
    email: str,
    username: str,
    first_name: str,
    last_name: str,
    password: str | None = None,
    language: str | None = None,
) -> None:
    try:
        await panel_db.update_user(
            db,
            user_id,
            email=email,
            username=username,
            first_name=first_name,
            last_name=last_name,
            password=password,
            language=language,
        )
    except PanelDBError as exc:
        raise LifecycleError(str(exc)) from exc


async def delete_user(db: AsyncSession, user_id: int) -> None:
    """Delete a user (servers must already be gone)."""
    try:
        await panel_db.delete_user(db, user_id)
    except PanelDBError as exc:
        raise LifecycleError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Servers
# ---------------------------------------------------------------------------


async def create_server(
    db: AsyncSession,
    *,
    owner_id: int,
    node_id: int,
    allocation_id: int,
    egg_id: int,
    nest_id: int,
    name: str,
    description: str = "",
    memory: int,
    swap: int = 0,
    disk: int,
    io: int = 500,
    cpu: int,
    image: str,
    startup: str,
    environment: dict[str, str],
    database_limit: int = 0,
    backup_limit: int = 0,
    allocation_limit: int | None = None,
    skip_scripts: bool = False,
    oom_disabled: bool = True,
    threads: str | None = None,
    external_id: str | None = None,
    allocation_additional: list[int] | None = None,
    start_on_completion: bool = False,
) -> CreatedServer:
    """Insert server + variables, then notify Wings (reverse-pull).

    On Wings failure: rollback the panel DB rows so the operator can retry.
    Caller is responsible for ``db.commit()`` after this returns successfully.
    """
    try:
        created = await panel_db.create_server(
            db,
            owner_id=owner_id,
            node_id=node_id,
            allocation_id=allocation_id,
            egg_id=egg_id,
            nest_id=nest_id,
            name=name,
            description=description,
            memory=memory,
            swap=swap,
            disk=disk,
            io=io,
            cpu=cpu,
            image=image,
            startup=startup,
            environment=environment,
            database_limit=database_limit,
            backup_limit=backup_limit,
            allocation_limit=allocation_limit,
            skip_scripts=skip_scripts,
            oom_disabled=oom_disabled,
            threads=threads,
            external_id=external_id,
            allocation_additional=allocation_additional,
        )
    except PanelDBError as exc:
        raise _wrap_panel_db(exc) from exc

    # Commit so Wings (which calls back panel via Remote API) can see the row
    await db.commit()

    try:
        await wings_service.create_server(
            db, node_id, created.uuid, start_on_completion=start_on_completion
        )
    except WingsServiceError as exc:
        # Rollback: delete the server row we just inserted
        logger.exception("Wings create_server failed, rolling back panel rows")
        try:
            await panel_db.delete_server_row(db, created.id)
            await db.commit()
        except Exception:
            logger.exception(
                "Failed to rollback server %s after Wings failure", created.id
            )
        raise LifecycleError(f"Wings 创建失败: {exc}") from exc

    return created


async def _resolve_server(db: AsyncSession, server_id: int) -> tuple[str, int]:
    """Resolve (uuid, node_id) and translate PanelDBError into LifecycleError.

    Without this wrapper a missing server bubbles up as PanelDBError and
    bypasses the LifecycleError-only handlers used in batch routes.
    """
    try:
        return await panel_db.get_server_uuid_and_node(db, server_id)
    except PanelDBError as exc:
        raise LifecycleError(str(exc)) from exc


def _wrap_panel_db(exc: PanelDBError) -> LifecycleError:
    """Translate panel_db exceptions while preserving the validation/operational split."""
    if isinstance(exc, PanelDBValidationError):
        return LifecycleValidationError(str(exc))
    return LifecycleError(str(exc))


async def suspend_server(db: AsyncSession, server_id: int) -> None:
    """Suspend on Wings first, then mark in DB. Compensating rollback on Wings failure."""
    uuid, node_id = await _resolve_server(db, server_id)
    # Read previous status so we can compensate if Wings fails after our DB write
    prev_status_row = await db.execute(
        text("SELECT status FROM servers WHERE id=:sid").bindparams(sid=server_id)
    )
    prev_status = prev_status_row.scalar()
    try:
        await panel_db.set_server_status(db, server_id, "suspended")
    except PanelDBError as exc:
        raise LifecycleError(str(exc)) from exc
    await db.commit()
    try:
        await wings_service.sync_server(db, node_id, uuid)
    except WingsServiceError as exc:
        # Compensate: revert DB so automation/UI reflect Wings reality
        try:
            await panel_db.set_server_status(db, server_id, prev_status)
            await db.commit()
        except Exception:
            logger.exception(
                "Failed to compensate suspend rollback for server %s", server_id
            )
        raise LifecycleError(f"Wings sync 失败: {exc}") from exc


async def unsuspend_server(db: AsyncSession, server_id: int) -> None:
    """Clear suspended on Wings first, then mark in DB. Compensating rollback on Wings failure."""
    uuid, node_id = await _resolve_server(db, server_id)
    prev_status_row = await db.execute(
        text("SELECT status FROM servers WHERE id=:sid").bindparams(sid=server_id)
    )
    prev_status = prev_status_row.scalar()
    try:
        await panel_db.set_server_status(db, server_id, None)
    except PanelDBError as exc:
        raise LifecycleError(str(exc)) from exc
    await db.commit()
    try:
        await wings_service.sync_server(db, node_id, uuid)
    except WingsServiceError as exc:
        try:
            await panel_db.set_server_status(db, server_id, prev_status)
            await db.commit()
        except Exception:
            logger.exception(
                "Failed to compensate unsuspend rollback for server %s", server_id
            )
        raise LifecycleError(f"Wings sync 失败: {exc}") from exc


async def reinstall_server(db: AsyncSession, server_id: int) -> None:
    """Mark for reinstall in DB, then trigger Wings. Compensating rollback on Wings failure.

    Reinstall sets status='installing' + installed_at=NULL; if Wings can't be
    reached we restore both fields so monitoring/automation don't see the
    server stuck in installing forever.
    """
    uuid, node_id = await _resolve_server(db, server_id)
    prev_row = await db.execute(
        text("SELECT status, installed_at FROM servers WHERE id=:sid").bindparams(
            sid=server_id
        )
    )
    prev = prev_row.first()
    prev_status = prev[0] if prev else None
    prev_installed_at = prev[1] if prev else None
    try:
        await panel_db.mark_for_reinstall(db, server_id)
    except PanelDBError as exc:
        raise LifecycleError(str(exc)) from exc
    await db.commit()
    try:
        await wings_service.reinstall_server(db, node_id, uuid)
    except WingsServiceError as exc:
        try:
            await db.execute(
                text(
                    "UPDATE servers SET status=:st, installed_at=:ia, updated_at=NOW() "
                    "WHERE id=:sid"
                ).bindparams(st=prev_status, ia=prev_installed_at, sid=server_id)
            )
            await db.commit()
        except Exception:
            logger.exception(
                "Failed to compensate reinstall rollback for server %s", server_id
            )
        raise LifecycleError(f"Wings reinstall 失败: {exc}") from exc


async def update_server_build(
    db: AsyncSession,
    server_id: int,
    *,
    memory: int | None = None,
    swap: int | None = None,
    disk: int | None = None,
    io: int | None = None,
    cpu: int | None = None,
    allocation_limit: int | None = None,
    database_limit: int | None = None,
    backup_limit: int | None = None,
) -> None:
    """Modify a server's resource limits (memory/swap/disk/io/cpu, plus the
    feature limits) and tell Wings to re-pull its config.

    Mirrors Pterodactyl's ``BuildModificationService``: panel DB write first,
    then ``POST /api/servers/{uuid}/sync`` so Wings recreates the container
    with the new cgroup limits at next start. If Wings fails we restore the
    previous limits to keep DB and node aligned.
    """
    uuid, node_id = await _resolve_server(db, server_id)
    # Snapshot the previous limits so we can compensate on Wings failure.
    prev_row = await db.execute(
        text(
            "SELECT memory, swap, disk, io, cpu, allocation_limit, "
            "database_limit, backup_limit FROM servers WHERE id=:sid"
        ).bindparams(sid=server_id)
    )
    prev = prev_row.first()
    if prev is None:
        raise LifecycleError(f"服务器 {server_id} 不存在")
    prev_values = {
        "memory": prev[0],
        "swap": prev[1],
        "disk": prev[2],
        "io": prev[3],
        "cpu": prev[4],
        "allocation_limit": prev[5],
        "database_limit": prev[6],
        "backup_limit": prev[7],
    }

    try:
        await panel_db.update_server_limits(
            db,
            server_id,
            memory=memory,
            swap=swap,
            disk=disk,
            io=io,
            cpu=cpu,
            allocation_limit=allocation_limit,
            database_limit=database_limit,
            backup_limit=backup_limit,
        )
    except PanelDBError as exc:
        raise _wrap_panel_db(exc) from exc
    await db.commit()

    try:
        await wings_service.sync_server(db, node_id, uuid)
    except WingsServiceError as exc:
        # Compensate: revert the limits so DB and node stay consistent.
        try:
            await panel_db.update_server_limits(db, server_id, **prev_values)
            await db.commit()
        except Exception:
            logger.exception(
                "Failed to compensate build-modification rollback for server %s",
                server_id,
            )
        raise LifecycleError(f"Wings sync 失败: {exc}") from exc


async def delete_server(db: AsyncSession, server_id: int) -> None:
    """Destroy a server completely, mirroring Pterodactyl's ``ServerDeletionService``.

    Order of operations is chosen so that an early failure leaves the server
    object intact and retryable. Anything that is **irreversible on the remote
    side** (e.g. ``DROP DATABASE``) only runs AFTER Wings has successfully
    destroyed the container/volume.

    1. Delete every backup archive on the node (Wings ``DELETE
       /api/servers/{uuid}/backup/{backup_uuid}``). Failures are logged but
       do not block — leftover archives are recoverable manually.
    2. Destroy the Wings container/volume. 404 → success; any other error is
       fatal so the operator can retry.
    3. DROP every per-server MySQL database + user on its remote host, then
       remove the corresponding ``databases`` rows. By this point Wings is
       already gone, so a remote-DB failure cannot leave the server in a
       half-deleted state where users still see it but its DB is missing.
    4. Delete the panel ``servers`` row (FK CASCADE handles
       ``server_variables`` / ``manager_server_meta`` / ``backups``;
       allocations FK ``ON DELETE SET NULL`` releases the ports).
    """
    try:
        uuid, node_id = await panel_db.get_server_uuid_and_node(db, server_id)
    except PanelDBError:
        # Server already gone from DB
        return

    # 1. Delete physical backup archives on the node (best-effort)
    from sqlalchemy import select as sql_select

    from app.db.models.pterodactyl import Backup

    backups = (
        await db.execute(sql_select(Backup).where(Backup.server_id == server_id))
    ).scalars().all()
    for backup in backups:
        try:
            await wings_service.delete_backup(db, node_id, uuid, str(backup.uuid))
        except WingsServiceError as exc:
            logger.warning(
                "Wings delete_backup failed for server %s backup %s: %s",
                server_id, backup.uuid, exc,
            )

    # 2. Destroy Wings container/volume — failure is fatal so the operator
    #    can retry. delete_server is idempotent (404 → success), so a true
    #    failure here means the node is unreachable or returned 5xx.
    try:
        await wings_service.delete_server(db, node_id, uuid)
    except WingsServiceError as exc:
        raise LifecycleError(f"Wings 删除失败: {exc}") from exc

    # 3. DROP remote MySQL databases. Wings is already gone, so we MUST go
    #    on to delete the panel ``servers`` row regardless — leaving the
    #    server in the panel after its container is destroyed would show
    #    users a "ghost" they can't start. ``drop_server_databases`` is
    #    best-effort: it returns a list of remote-DB errors that we log /
    #    surface but do not turn into a hard failure.
    db_errors: list[str] = []
    try:
        _removed, db_errors = await drop_server_databases(db, server_id)
    except PanelDatabaseError as exc:
        # Connection-level failure (e.g. host row decrypt). Log and proceed.
        logger.error(
            "drop_server_databases hard-failed server=%s: %s — proceeding to "
            "delete panel row anyway since Wings container is already gone",
            server_id, exc,
        )
        db_errors = [f"远端数据库清理整体失败: {exc}"]

    # 4. Delete panel rows
    try:
        await panel_db.delete_server_row(db, server_id)
    except PanelDBError as exc:
        raise LifecycleError(str(exc)) from exc
    await db.commit()

    if db_errors:
        # Wings + panel row are already gone — server is fully deleted from
        # the user's perspective. The leftover remote MySQL artefacts are an
        # operator-only concern; log loudly so monitoring can pick it up but
        # do NOT turn the user-facing delete into a 502.
        logger.error(
            "server=%s deleted with %d leftover remote-DB issue(s):\n  - %s",
            server_id, len(db_errors), "\n  - ".join(db_errors),
        )
        # Surface to the activity log so admins can see it in the UI.
        await log_manager_activity(
            db,
            actor="system",
            action="delete_server_remote_db",
            status="warning",
            detail_key="server.delete.remote_db_leftover",
            detail_params={"server_id": server_id, "errors": db_errors[:10]},
        )


async def update_server_expiration_description(
    db: AsyncSession,
    server_id: int,
    expiration: date | None,
) -> None:
    """Sync the 到期时间 line in servers.description. Pure DB write, no Wings."""
    iso = expiration.strftime("%Y/%m/%d") if expiration else None
    try:
        await panel_db.sync_server_expiration_description(db, server_id, iso)
    except PanelDBError as exc:
        raise LifecycleError(str(exc)) from exc
