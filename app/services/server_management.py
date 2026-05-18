"""Admin server-detail mutations backed by direct panel DB writes."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete as sql_delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Allocation, Egg, EggVariable, ManagerHost, Nest, PteroServer, PteroUser, ServerVariable
from app.db.models.billing import BillingPlan
from app.schemas.admin_server_detail import (
    AdminServerDetailResponse,
    AdminServerSummary,
    DockerImageOption,
    ManagerHostSummary,
    ServerAllocationSummary,
    ServerEggSummary,
    ServerNestSummary,
    ServerNodeSummary,
    ServerOwnerSummary,
    ServerRuntimeResponse,
    ServerVariableSummary,
)
from app.services.egg_validator import EggValidationError, validate_environment
from app.services.server_lifecycle import (
    LifecycleError,
    LifecycleValidationError,
    update_server_build as lifecycle_update_server_build,
)
from app.services.wings import WingsServiceError, wings_service

logger = logging.getLogger(__name__)


class ServerManagementError(RuntimeError):
    """Raised when an admin server-detail operation cannot be completed."""


class ServerManagementValidationError(ServerManagementError):
    """Raised for caller-correctable input errors."""


class ServerNotFoundError(ServerManagementValidationError):
    """Raised when the requested server id does not exist.

    Subclass of ``ServerManagementValidationError`` so existing callers that
    catch the parent still work, but routers can map this specifically to
    HTTP 404 instead of 422. (Audit M3.)
    """


def _now() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


async def _get_server(db: AsyncSession, server_id: int) -> PteroServer:
    result = await db.execute(
        select(PteroServer)
        .options(selectinload(PteroServer.meta))
        .where(PteroServer.id == server_id)
    )
    server = result.scalar_one_or_none()
    if server is None:
        raise ServerNotFoundError(f"服务器 {server_id} 不存在")
    return server


def _parse_docker_images(raw: str | None) -> list[DockerImageOption]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        return [
            DockerImageOption(label=str(label), value=str(value))
            for label, value in payload.items()
            if value
        ]
    if isinstance(payload, list):
        return [
            DockerImageOption(label=str(value), value=str(value))
            for value in payload
            if value
        ]
    return []


async def get_server_detail(db: AsyncSession, server_id: int) -> AdminServerDetailResponse:
    server = await _get_server(db, server_id)

    nest = await db.get(Nest, int(server.nest_id)) if server.nest_id is not None else None
    manager_host = (
        await db.execute(
            select(ManagerHost).where(ManagerHost.pterodactyl_node_id == server.node_id)
        )
    ).scalar_one_or_none()

    allocation_rows = await db.execute(
        select(Allocation)
        .where(or_(Allocation.server_id == server_id, Allocation.id == server.allocation_id))
        .order_by(Allocation.id.asc())
    )
    allocations = list(allocation_rows.scalars().all())
    allocations.sort(key=lambda item: (item.id != server.allocation_id, item.id))

    variable_rows = await db.execute(
        select(EggVariable, ServerVariable.variable_value)
        .outerjoin(
            ServerVariable,
            and_(
                ServerVariable.variable_id == EggVariable.id,
                ServerVariable.server_id == server_id,
            ),
        )
        .where(EggVariable.egg_id == server.egg_id)
        .order_by(EggVariable.id.asc())
    )
    variable_pairs = list(variable_rows.all())

    plan_id = server.meta.plan_id if server.meta is not None else None
    plan_obj: BillingPlan | None = None
    if plan_id is not None:
        plan_obj = await db.get(BillingPlan, plan_id)

    return AdminServerDetailResponse(
        server=AdminServerSummary(
            id=int(server.id),
            uuid=server.uuid,
            uuid_short=server.uuid_short,
            external_id=server.external_id,
            name=server.name,
            description=server.description or "",
            status=server.status,
            is_suspended=server.is_suspended,
            is_installing=server.status == "installing" or server.installed_at is None,
            owner_id=int(server.owner_id),
            node_id=int(server.node_id),
            nest_id=int(server.nest_id),
            egg_id=int(server.egg_id),
            allocation_id=int(server.allocation_id),
            memory=int(server.memory),
            swap=int(server.swap),
            disk=int(server.disk),
            io=int(server.io),
            cpu=int(server.cpu),
            threads=server.threads,
            oom_disabled=bool(server.oom_disabled),
            allocation_limit=server.allocation_limit,
            database_limit=server.database_limit,
            backup_limit=int(server.backup_limit),
            image=server.image,
            startup=server.startup,
            skip_scripts=bool(server.skip_scripts),
            created_at=server.created_at,
            updated_at=server.updated_at,
            installed_at=server.installed_at,
            expiration_date=server.expiration_date.isoformat() if server.expiration_date else None,
            plan_id=plan_id,
            plan_code=plan_obj.code if plan_obj else None,
            plan_name=plan_obj.display_name if plan_obj else None,
        ),
        owner=ServerOwnerSummary(
            id=int(server.owner.id),
            uuid=server.owner.uuid,
            username=server.owner.username,
            email=server.owner.email,
        ),
        node=ServerNodeSummary(
            id=int(server.node.id),
            name=server.node.name,
            fqdn=server.node.fqdn,
            scheme=server.node.scheme,
            daemon_listen=int(server.node.daemon_listen),
            daemon_sftp=int(server.node.daemon_sftp),
        ),
        nest=ServerNestSummary(id=int(nest.id), name=nest.name) if nest else None,
        egg=ServerEggSummary(
            id=int(server.egg.id),
            name=server.egg.name,
            nest_id=int(server.egg.nest_id),
            startup=server.egg.startup,
            docker_images=_parse_docker_images(server.egg.docker_images),
        ),
        manager_host=(
            ManagerHostSummary(
                id=int(manager_host.id),
                name=manager_host.name,
                agent_url=manager_host.agent_url,
                enabled=bool(manager_host.enabled),
            )
            if manager_host
            else None
        ),
        allocations=[
            ServerAllocationSummary(
                id=int(allocation.id),
                node_id=int(allocation.node_id),
                ip=allocation.ip,
                ip_alias=allocation.ip_alias,
                port=int(allocation.port),
                notes=allocation.notes,
                is_primary=allocation.id == server.allocation_id,
            )
            for allocation in allocations
        ],
        variables=[
            ServerVariableSummary(
                id=int(variable.id),
                name=variable.name,
                description=variable.description,
                env_variable=variable.env_variable,
                default_value=variable.default_value,
                value=(value if value is not None else variable.default_value) or "",
                rules=variable.rules,
                user_viewable=bool(variable.user_viewable),
                user_editable=bool(variable.user_editable),
            )
            for variable, value in variable_pairs
        ],
        hidden_variable_count=sum(1 for variable, _ in variable_pairs if not variable.user_viewable),
    )


async def get_runtime(db: AsyncSession, server_id: int) -> ServerRuntimeResponse:
    server = await _get_server(db, server_id)
    data = await wings_service.get_server(db, server.node_id, server.uuid)
    return ServerRuntimeResponse(
        state=str(data.get("state") or "offline"),
        is_suspended=bool(data.get("is_suspended", server.is_suspended)),
        resources=data.get("utilization") or data.get("resources") or {},
        raw=data,
    )


async def list_available_allocations(
    db: AsyncSession, server_id: int
) -> list[ServerAllocationSummary]:
    server = await _get_server(db, server_id)
    rows = await db.execute(
        select(Allocation)
        .where(Allocation.node_id == server.node_id, Allocation.server_id.is_(None))
        .order_by(Allocation.ip.asc(), Allocation.port.asc())
    )
    return [
        ServerAllocationSummary(
            id=int(allocation.id),
            node_id=int(allocation.node_id),
            ip=allocation.ip,
            ip_alias=allocation.ip_alias,
            port=int(allocation.port),
            notes=allocation.notes,
            is_primary=False,
        )
        for allocation in rows.scalars().all()
    ]


async def update_details(
    db: AsyncSession,
    server_id: int,
    *,
    name: str | None,
    description: str | None,
    external_id: str | None,
    provided: set[str],
) -> None:
    server = await _get_server(db, server_id)
    if "name" in provided:
        value = (name or "").strip()
        if not value:
            raise ServerManagementValidationError("服务器名称不能为空")
        server.name = value
    if "description" in provided:
        server.description = description or ""
    if "external_id" in provided or "externalId" in provided:
        server.external_id = (external_id or "").strip() or None
    server.updated_at = _now()
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServerManagementValidationError("external_id 已被占用") from exc


async def update_owner(
    db: AsyncSession,
    server_id: int,
    *,
    owner_id: int,
) -> str | None:
    server = await _get_server(db, server_id)
    old_owner_uuid = server.owner.uuid
    old_owner_id = int(server.owner_id)
    owner = await db.get(PteroUser, owner_id)
    if owner is None:
        raise ServerManagementValidationError(f"用户 {owner_id} 不存在")
    if old_owner_id == owner_id:
        return None

    node_id = int(server.node_id)
    server_uuid = server.uuid
    server.owner_id = owner_id
    server.updated_at = _now()
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServerManagementValidationError("服务器所有者更新失败") from exc

    try:
        await wings_service.deauthorize_user(
            db,
            node_id,
            old_owner_uuid,
            server_uuids=[server_uuid],
        )
    except WingsServiceError as exc:
        logger.warning(
            "Failed to deauthorize old owner %s for server %s: %s",
            old_owner_uuid,
            server_id,
            exc,
        )
        return "服务器所有者已更新，但旧所有者的 Wings 会话撤销失败"
    return None


async def update_build(
    db: AsyncSession,
    server_id: int,
    *,
    memory: int | None = None,
    swap: int | None = None,
    disk: int | None = None,
    io: int | None = None,
    cpu: int | None = None,
    threads: str | None = None,
    update_threads: bool = False,
    oom_disabled: bool | None = None,
    allocation_limit: int | None = None,
    database_limit: int | None = None,
    backup_limit: int | None = None,
) -> None:
    try:
        await lifecycle_update_server_build(
            db,
            server_id,
            memory=memory,
            swap=swap,
            disk=disk,
            io=io,
            cpu=cpu,
            threads=threads,
            update_threads=update_threads,
            oom_disabled=oom_disabled,
            allocation_limit=allocation_limit,
            database_limit=database_limit,
            backup_limit=backup_limit,
        )
    except LifecycleValidationError as exc:
        raise ServerManagementValidationError(str(exc)) from exc
    except LifecycleError as exc:
        raise ServerManagementError(str(exc)) from exc


async def _allocation_snapshot(
    db: AsyncSession,
    server: PteroServer,
    extra_allocation_ids: list[int] | None = None,
) -> dict[str, Any]:
    ids = {int(server.allocation_id)}
    if extra_allocation_ids:
        ids.update(int(item) for item in extra_allocation_ids)
    rows = await db.execute(
        select(Allocation).where(or_(Allocation.server_id == server.id, Allocation.id.in_(ids)))
    )
    states = {
        int(allocation.id): {
            "server_id": allocation.server_id,
            "notes": allocation.notes,
        }
        for allocation in rows.scalars().all()
    }
    return {"allocation_id": int(server.allocation_id), "states": states}


async def _restore_allocations(
    db: AsyncSession, server_id: int, snapshot: dict[str, Any]
) -> None:
    server = await db.get(PteroServer, server_id)
    if server is not None:
        server.allocation_id = snapshot["allocation_id"]
        server.updated_at = _now()
    for allocation_id, state in snapshot["states"].items():
        allocation = await db.get(Allocation, allocation_id)
        if allocation is not None:
            allocation.server_id = state["server_id"]
            allocation.notes = state["notes"]
            allocation.updated_at = _now()
    await db.flush()


async def _server_config_snapshot(
    db: AsyncSession, server: PteroServer
) -> dict[str, Any]:
    variable_rows = await db.execute(
        select(ServerVariable).where(ServerVariable.server_id == server.id)
    )
    return {
        "server": {
            "nest_id": server.nest_id,
            "egg_id": server.egg_id,
            "image": server.image,
            "startup": server.startup,
            "skip_scripts": server.skip_scripts,
        },
        "variables": [
            {
                "variable_id": row.variable_id,
                "variable_value": row.variable_value,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row in variable_rows.scalars().all()
        ],
    }


async def _restore_server_config(
    db: AsyncSession, server_id: int, snapshot: dict[str, Any]
) -> None:
    server = await db.get(PteroServer, server_id)
    if server is not None:
        for field, value in snapshot["server"].items():
            setattr(server, field, value)
        server.updated_at = _now()
    await db.execute(sql_delete(ServerVariable).where(ServerVariable.server_id == server_id))
    for row in snapshot["variables"]:
        db.add(
            ServerVariable(
                server_id=server_id,
                variable_id=row["variable_id"],
                variable_value=row["variable_value"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        )
    await db.flush()


async def _commit_then_sync_server(
    db: AsyncSession,
    server: PteroServer,
    *,
    snapshot: dict[str, Any] | None = None,
    restore_kind: str | None = None,
) -> None:
    server_id = int(server.id)
    node_id = int(server.node_id)
    server_uuid = server.uuid
    await db.commit()
    try:
        await wings_service.sync_server(db, node_id, server_uuid)
    except WingsServiceError as exc:
        if snapshot is not None:
            try:
                if restore_kind == "server_config":
                    await _restore_server_config(db, server_id, snapshot)
                else:
                    await _restore_allocations(db, server_id, snapshot)
                await db.commit()
            except Exception:
                logger.exception("Failed to restore server %s after Wings sync failure", server_id)
        raise ServerManagementError(f"Wings sync 失败: {exc}") from exc


async def add_allocations(
    db: AsyncSession,
    server_id: int,
    *,
    allocation_ids: list[int],
) -> None:
    server = await _get_server(db, server_id)
    unique_ids = list(dict.fromkeys(int(item) for item in allocation_ids))
    snapshot = await _allocation_snapshot(db, server, unique_ids)
    for allocation_id in unique_ids:
        allocation = await db.get(Allocation, allocation_id)
        if allocation is None:
            raise ServerManagementValidationError(f"分配 {allocation_id} 不存在")
        if allocation.node_id != server.node_id:
            raise ServerManagementValidationError(f"分配 {allocation_id} 不属于当前节点")
        if allocation.server_id not in (None, server_id):
            raise ServerManagementValidationError(
                f"分配 {allocation_id} 已被服务器 {allocation.server_id} 占用"
            )
        allocation.server_id = server_id
        allocation.updated_at = _now()
    server.updated_at = _now()
    await db.flush()
    await _commit_then_sync_server(db, server, snapshot=snapshot)


async def remove_allocation(db: AsyncSession, server_id: int, allocation_id: int) -> None:
    server = await _get_server(db, server_id)
    if int(server.allocation_id) == int(allocation_id):
        raise ServerManagementValidationError("不能移除主分配，请先切换主分配")
    allocation = await db.get(Allocation, allocation_id)
    if allocation is None or allocation.server_id != server_id:
        raise ServerManagementValidationError(f"分配 {allocation_id} 不属于该服务器")

    snapshot = await _allocation_snapshot(db, server, [allocation_id])
    allocation.server_id = None
    allocation.notes = None
    allocation.updated_at = _now()
    server.updated_at = _now()
    await db.flush()
    await _commit_then_sync_server(db, server, snapshot=snapshot)


async def set_primary_allocation(
    db: AsyncSession, server_id: int, allocation_id: int
) -> None:
    server = await _get_server(db, server_id)
    allocation = await db.get(Allocation, allocation_id)
    if allocation is None:
        raise ServerManagementValidationError(f"分配 {allocation_id} 不存在")
    if allocation.node_id != server.node_id:
        raise ServerManagementValidationError(f"分配 {allocation_id} 不属于当前节点")
    if allocation.server_id not in (None, server_id):
        raise ServerManagementValidationError(
            f"分配 {allocation_id} 已被服务器 {allocation.server_id} 占用"
        )

    snapshot = await _allocation_snapshot(db, server, [allocation_id])
    allocation.server_id = server_id
    allocation.updated_at = _now()
    server.allocation_id = allocation_id
    server.updated_at = _now()
    await db.flush()
    await _commit_then_sync_server(db, server, snapshot=snapshot)


async def update_startup(
    db: AsyncSession,
    server_id: int,
    *,
    image: str | None,
    startup: str | None,
    skip_scripts: bool | None,
    provided: set[str],
) -> None:
    server = await _get_server(db, server_id)
    snapshot = await _server_config_snapshot(db, server)
    if "image" in provided:
        value = (image or "").strip()
        if not value:
            raise ServerManagementValidationError("Docker 镜像不能为空")
        server.image = value
    if "startup" in provided:
        value = (startup or "").strip()
        if not value:
            raise ServerManagementValidationError("启动命令不能为空")
        server.startup = value
    if "skip_scripts" in provided or "skipScripts" in provided:
        server.skip_scripts = bool(skip_scripts)
    server.updated_at = _now()
    await db.flush()
    await _commit_then_sync_server(db, server, snapshot=snapshot, restore_kind="server_config")


async def switch_egg(
    db: AsyncSession,
    server_id: int,
    *,
    nest_id: int,
    egg_id: int,
    environment: dict[str, str],
    image: str | None,
    startup: str | None,
    skip_scripts: bool | None,
    provided: set[str],
) -> None:
    server = await _get_server(db, server_id)
    snapshot = await _server_config_snapshot(db, server)
    egg = await db.get(Egg, egg_id)
    if egg is None:
        raise ServerManagementValidationError(f"Egg {egg_id} 不存在")
    if int(egg.nest_id) != int(nest_id):
        raise ServerManagementValidationError(
            f"Egg {egg_id} 实际归属 nest {egg.nest_id}，与传入 nestId 不一致"
        )

    variable_rows = await db.execute(
        select(EggVariable).where(EggVariable.egg_id == egg_id).order_by(EggVariable.id.asc())
    )
    egg_variables = list(variable_rows.scalars().all())
    values: dict[int, str] = {}
    for variable in egg_variables:
        value = environment.get(variable.env_variable, variable.default_value)
        if value is None:
            value = variable.default_value
        try:
            validate_environment(variable.env_variable, str(value), variable.rules)
        except EggValidationError as exc:
            raise ServerManagementValidationError(str(exc)) from exc
        values[int(variable.id)] = str(value)

    server.nest_id = int(nest_id)
    server.egg_id = int(egg_id)
    if "image" in provided:
        value = (image or "").strip()
        if not value:
            raise ServerManagementValidationError("Docker 镜像不能为空")
        server.image = value
    if "startup" in provided:
        value = (startup or "").strip()
        if not value:
            raise ServerManagementValidationError("启动命令不能为空")
        server.startup = value
    if "skip_scripts" in provided or "skipScripts" in provided:
        server.skip_scripts = bool(skip_scripts)
    server.updated_at = _now()

    await db.execute(sql_delete(ServerVariable).where(ServerVariable.server_id == server_id))
    for variable in egg_variables:
        db.add(
            ServerVariable(
                server_id=server_id,
                variable_id=int(variable.id),
                variable_value=values[int(variable.id)],
                created_at=_now(),
                updated_at=_now(),
            )
        )
    await db.flush()
    await _commit_then_sync_server(db, server, snapshot=snapshot, restore_kind="server_config")


async def update_variables(
    db: AsyncSession,
    server_id: int,
    *,
    variables: dict[str, str],
) -> None:
    server = await _get_server(db, server_id)
    snapshot = await _server_config_snapshot(db, server)
    variable_rows = await db.execute(
        select(EggVariable).where(EggVariable.egg_id == server.egg_id)
    )
    egg_variables = {variable.env_variable: variable for variable in variable_rows.scalars().all()}
    unknown = sorted(set(variables) - set(egg_variables))
    if unknown:
        raise ServerManagementValidationError(f"未知变量: {', '.join(unknown)}")

    existing_rows = await db.execute(
        select(ServerVariable).where(ServerVariable.server_id == server_id)
    )
    existing = {
        int(server_variable.variable_id): server_variable
        for server_variable in existing_rows.scalars().all()
    }

    for env_name, value in variables.items():
        egg_variable = egg_variables[env_name]
        value = "" if value is None else str(value)
        try:
            validate_environment(egg_variable.env_variable, value, egg_variable.rules)
        except EggValidationError as exc:
            raise ServerManagementValidationError(str(exc)) from exc

        server_variable = existing.get(int(egg_variable.id))
        if server_variable is None:
            db.add(
                ServerVariable(
                    server_id=server_id,
                    variable_id=int(egg_variable.id),
                    variable_value=value,
                    created_at=_now(),
                    updated_at=_now(),
                )
            )
        else:
            server_variable.variable_value = value
            server_variable.updated_at = _now()

    server.updated_at = _now()
    await db.flush()
    await _commit_then_sync_server(db, server, snapshot=snapshot, restore_kind="server_config")
