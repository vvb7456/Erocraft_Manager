from __future__ import annotations

import logging
import uuid as _uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import date
from typing import Any

from sqlalchemy import delete as sql_delete, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.config.egg_credentials import validate_startup_variable
from app.core.contracts import OperationResult
from app.core.time import format_in_timezone, get_runtime_timezone, utc_naive_now, utc_naive_now_sec
from app.db.models.billing import BillingPlan
from app.db.models.pterodactyl import (
    Allocation,
    Backup,
    Egg,
    EggVariable,
    PanelNode,
    PteroServer,
    PteroUser,
    ServerVariable,
)
from app.db.repositories.allocation_reservations import (
    is_allocation_actively_reserved,
    restore_order_strong_reservations,
)
from app.services.billing.plan_snapshot import build_plan_snapshot
from app.services.egg_validator import EggValidationError, validate_environment
from app.services.runtime import (
    InstanceRuntimeAdapter,
    RuntimeError as RuntimeAdapterError,
    wings_runtime_adapter,
)
from app.services.server_engine import hooks
from app.services.server_engine.errors import (
    ServerConflictError,
    ServerForbiddenError,
    ServerNotFoundError,
    ServerRuntimeSyncError,
    ServerValidationError,
)
from app.services.server_engine.types import (
    CreatedServer,
    DeleteResult,
    InstallCompletedResult,
    MutationResult,
    RenewResult,
    ServerBuildPatch,
    VariableChange,
    VariablesUpdateResult,
)
from app.services.user_service import mark_user_owned_server

logger = logging.getLogger(__name__)


def _is_retryable_lock_error(exc: OperationalError) -> bool:
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", ())
    code = args[0] if args and isinstance(args[0], int) else None
    # 1020: MariaDB 11.8 ER_CHECKREAD; 1213: InnoDB deadlock
    return code in (1020, 1213)


class ServerLifecycleEngine:
    def __init__(self, runtime: InstanceRuntimeAdapter = wings_runtime_adapter) -> None:
        self._runtime = runtime

    async def _get_server_or_404(
        self, db: AsyncSession, server_id: int, *, for_update: bool = False
    ) -> PteroServer:
        stmt = select(PteroServer).where(PteroServer.id == server_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        server = (await db.execute(stmt)).scalar_one_or_none()
        if server is None:
            raise ServerNotFoundError(f"服务器 {server_id} 不存在")
        return server

    @staticmethod
    def _build_fields_from_patch(patch: ServerBuildPatch) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        for attr in ("memory", "swap", "disk", "io", "cpu", "allocation_limit", "database_limit", "backup_limit"):
            val = getattr(patch, attr)
            if val is not None:
                fields[attr] = int(val)
        if patch.update_threads:
            fields["threads"] = patch.threads if patch.threads else None
        if patch.oom_disabled is not None:
            fields["oom_disabled"] = bool(patch.oom_disabled)
        return fields

    @staticmethod
    def _snapshot_build_and_plan(server: PteroServer) -> dict[str, Any]:
        return {
            "memory": int(server.memory),
            "swap": int(server.swap),
            "disk": int(server.disk),
            "io": int(server.io),
            "cpu": int(server.cpu),
            "allocation_limit": server.allocation_limit,
            "database_limit": server.database_limit,
            "backup_limit": int(server.backup_limit),
            "threads": server.threads,
            "oom_disabled": bool(server.oom_disabled),
            "plan_id": server.plan_id,
            "is_trial": bool(server.is_trial),
            "expiration_date": server.expiration_date,
        }

    async def _commit_and_sync_build_plan(
        self,
        db: AsyncSession,
        server: PteroServer,
        *,
        snapshot: dict[str, Any],
        sync_runtime: bool,
    ) -> None:
        server_id = int(server.id)
        node_id = int(server.node_id)
        server_uuid = server.uuid
        await db.commit()
        if not sync_runtime:
            return
        try:
            await self._runtime.sync_server(db, node_id, server_uuid)
        except RuntimeAdapterError as exc:
            try:
                await db.execute(
                    update(PteroServer)
                    .where(PteroServer.id == server_id)
                    .values(**snapshot, updated_at=utc_naive_now_sec())
                )
                await db.commit()
            except Exception:  # noqa: BLE001
                logger.exception("Failed to compensate build/plan rollback for server %s", server_id)
            raise ServerRuntimeSyncError(f"Wings sync 失败: {exc}") from exc

    @staticmethod
    async def _allocation_snapshot(
        db: AsyncSession, server: PteroServer, extra_allocation_ids: list[int] | None = None
    ) -> dict[str, Any]:
        ids = {int(server.allocation_id), *(int(i) for i in (extra_allocation_ids or ()))}
        rows = await db.execute(
            select(Allocation).where(or_(Allocation.server_id == server.id, Allocation.id.in_(ids)))
        )
        return {
            "allocation_id": int(server.allocation_id),
            "states": {
                int(a.id): {
                    "server_id": a.server_id,
                    "notes": a.notes,
                    "reserved_order_id": a.reserved_order_id,
                    "reserved_until": a.reserved_until,
                }
                for a in rows.scalars().all()
            },
        }

    @staticmethod
    async def _restore_allocations(db: AsyncSession, server_id: int, snapshot: dict[str, Any]) -> None:
        now = utc_naive_now_sec()
        server = await db.get(PteroServer, server_id)
        if server is not None:
            server.allocation_id = snapshot["allocation_id"]
            server.updated_at = now
        for allocation_id, state in snapshot["states"].items():
            allocation = await db.get(Allocation, allocation_id)
            if allocation is not None:
                allocation.server_id = state["server_id"]
                allocation.notes = state["notes"]
                allocation.reserved_order_id = state["reserved_order_id"]
                allocation.reserved_until = state["reserved_until"]
                allocation.updated_at = now
        await db.flush()

    @staticmethod
    async def _server_config_snapshot(db: AsyncSession, server: PteroServer) -> dict[str, Any]:
        var_rows = await db.execute(select(ServerVariable).where(ServerVariable.server_id == server.id))
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
                for row in var_rows.scalars().all()
            ],
        }

    @staticmethod
    async def _restore_server_config(db: AsyncSession, server_id: int, snapshot: dict[str, Any]) -> None:
        now = utc_naive_now_sec()
        server = await db.get(PteroServer, server_id)
        if server is not None:
            for field_name, value in snapshot["server"].items():
                setattr(server, field_name, value)
            server.updated_at = now
        await db.execute(sql_delete(ServerVariable).where(ServerVariable.server_id == server_id))
        for row in snapshot["variables"]:
            db.add(ServerVariable(server_id=server_id, **row))
        await db.flush()

    async def _commit_then_sync_server(
        self,
        db: AsyncSession,
        server: PteroServer,
        *,
        snapshot: dict[str, Any] | None = None,
        restore_kind: str | None = None,
    ) -> None:
        server_id, node_id, server_uuid = int(server.id), int(server.node_id), server.uuid
        await db.commit()
        try:
            await self._runtime.sync_server(db, node_id, server_uuid)
        except RuntimeAdapterError as exc:
            if snapshot is not None:
                try:
                    if restore_kind == "server_config":
                        await self._restore_server_config(db, server_id, snapshot)
                    else:
                        await self._restore_allocations(db, server_id, snapshot)
                    await db.commit()
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to compensate restore for server %s", server_id)
            raise ServerRuntimeSyncError(f"Wings sync 失败: {exc}") from exc

    async def _lock_and_validate_allocations(
        self, db: AsyncSession, server: PteroServer, allocation_ids: list[int], now: Any
    ) -> list[Allocation]:
        # 按 Allocation.id ASC 加行锁防并发死锁；回滚前提取字段避免过期属性懒加载报错。
        sorted_ids = sorted(set(allocation_ids))
        locked = list(
            (
                await db.scalars(
                    select(Allocation)
                    .where(Allocation.id.in_(sorted_ids))
                    .order_by(Allocation.id.asc())
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        alloc_map = {int(row.id): row for row in locked}
        result: list[Allocation] = []
        server_id = int(server.id)
        for aid in allocation_ids:
            alloc = alloc_map.get(aid)
            if alloc is None:
                await db.rollback()
                raise ServerValidationError(f"分配 {aid} 不存在")
            if alloc.node_id != server.node_id:
                await db.rollback()
                raise ServerValidationError(f"分配 {aid} 不属于当前节点")
            if alloc.server_id not in (None, server_id):
                occupied_by = alloc.server_id
                await db.rollback()
                raise ServerValidationError(f"分配 {aid} 已被服务器 {occupied_by} 占用")
            if alloc.server_id is None and is_allocation_actively_reserved(alloc, now):
                reserved_order_id = alloc.reserved_order_id
                await db.rollback()
                raise ServerValidationError(f"分配 {aid} 已被订单 #{reserved_order_id} 预留锁定")
            result.append(alloc)
        return result

    async def create_server_db_only(
        self,
        db: AsyncSession,
        *,
        owner_id: int,
        node_id: int,
        allocation_id: int,
        egg_id: int,
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
        consuming_order_id: int | None = None,
        expiration_date: date | None = None,
        plan_id: int | None = None,
        is_trial: bool = False,
    ) -> CreatedServer:
        """Flush-only DB insert for two-phase provisioning; caller owns ``db.commit()``."""
        if await db.get(PteroUser, owner_id) is None:
            raise ServerValidationError(f"用户 {owner_id} 不存在")
        if await db.get(PanelNode, node_id) is None:
            raise ServerValidationError(f"节点 {node_id} 不存在")
        egg = await db.get(Egg, egg_id)
        if egg is None:
            raise ServerValidationError(f"Egg {egg_id} 不存在")

        now = utc_naive_now_sec()
        primary_id = int(allocation_id)
        extra_ids = list(dict.fromkeys(int(eid) for eid in (allocation_additional or ()) if int(eid) != primary_id))
        requested_ids = sorted({primary_id, *extra_ids})

        locked_rows = list(
            (
                await db.scalars(
                    select(Allocation)
                    .where(Allocation.id.in_(requested_ids))
                    .order_by(Allocation.id.asc())
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        alloc_map = {int(row.id): row for row in locked_rows}

        def _validate_alloc(aid: int, *, label: str) -> Allocation:
            row = alloc_map.get(aid)
            if row is None:
                raise ServerValidationError(f"{label} {aid} 不存在")
            if row.node_id != node_id:
                raise ServerValidationError(f"{label} {aid} 不在节点 {node_id} 上（实际节点 {row.node_id}）")
            if row.server_id is not None:
                raise ServerValidationError(f"{label} {aid} 已被服务器 {row.server_id} 占用")
            if is_allocation_actively_reserved(row, now):
                if consuming_order_id is None or row.reserved_order_id != consuming_order_id:
                    raise ServerValidationError(f"{label} {aid} 已被订单 #{row.reserved_order_id} 预留锁定")
            return row

        alloc = _validate_alloc(primary_id, label="分配")
        additional_allocs = [_validate_alloc(eid, label="附加分配") for eid in extra_ids]

        egg_vars = list((await db.execute(select(EggVariable).where(EggVariable.egg_id == egg_id))).scalars().all())
        for ev in egg_vars:
            try:
                validate_environment(ev.env_variable, environment.get(ev.env_variable, ev.default_value), ev.rules)
            except EggValidationError as exc:
                raise ServerValidationError(str(exc)) from exc

        server_uuid = str(_uuid.uuid4())
        server = PteroServer(
            external_id=external_id,
            uuid=server_uuid,
            uuid_short=server_uuid.replace("-", "")[:8],
            node_id=node_id,
            name=name,
            description=description or "",
            status="installing",
            skip_scripts=skip_scripts,
            owner_id=owner_id,
            memory=int(memory),
            swap=int(swap),
            disk=int(disk),
            io=int(io),
            cpu=int(cpu),
            threads=threads,
            oom_disabled=bool(oom_disabled),
            allocation_id=primary_id,
            nest_id=egg.nest_id,
            egg_id=int(egg_id),
            startup=startup,
            image=image,
            allocation_limit=allocation_limit,
            database_limit=int(database_limit),
            backup_limit=int(backup_limit),
            created_at=now,
            updated_at=now,
            installed_at=None,
            expiration_date=expiration_date,
            plan_id=plan_id,
            is_trial=bool(is_trial),
        )
        db.add(server)
        try:
            await db.flush()
        except IntegrityError as exc:
            raise ServerConflictError(f"创建服务器失败: {exc.orig}") from exc

        server_id = int(server.id)
        for row in (alloc, *additional_allocs):
            row.server_id = server_id
            row.reserved_order_id = None
            row.reserved_until = None
            row.updated_at = now
        for ev in egg_vars:
            db.add(
                ServerVariable(
                    server_id=server_id,
                    variable_id=int(ev.id),
                    variable_value=str(environment.get(ev.env_variable, ev.default_value)),
                    created_at=now,
                    updated_at=now,
                )
            )
        await db.flush()
        return CreatedServer(
            id=server_id,
            uuid=server.uuid,
            uuid_short=server.uuid_short,
            name=server.name,
            owner_id=int(server.owner_id),
            node_id=int(server.node_id),
            allocation_id=int(server.allocation_id),
        )

    async def delete_server_row(self, db: AsyncSession, server_id: int) -> None:
        """Flush-only row deletion; FK releases allocations and cascades child rows."""
        await db.execute(
            update(Allocation)
            .where(Allocation.server_id == server_id)
            .values(notes=None, updated_at=utc_naive_now_sec())
        )
        await db.execute(sql_delete(PteroServer).where(PteroServer.id == server_id))
        await db.flush()

    async def create_server(
        self,
        db: AsyncSession,
        *,
        owner_id: int,
        node_id: int,
        allocation_id: int,
        egg_id: int,
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
        consuming_order_id: int | None = None,
        expiration_date: date | None = None,
        plan_id: int | None = None,
        is_trial: bool = False,
        start_on_completion: bool = False,
        plan_snapshot: Mapping[str, Any] | None = None,
        confirm_clean_on_runtime_failure: bool = False,
        restore_order_reservations_on_failure: bool = False,
        on_db_created: Callable[[AsyncSession, CreatedServer], Awaitable[None]] | None = None,
        on_db_compensated: Callable[[AsyncSession, CreatedServer], Awaitable[None]] | None = None,
    ) -> CreatedServer:
        primary_id = int(allocation_id)
        extra_ids = list(dict.fromkeys(int(eid) for eid in (allocation_additional or ()) if int(eid) != primary_id))

        created = await self.create_server_db_only(
            db,
            owner_id=owner_id,
            node_id=node_id,
            allocation_id=primary_id,
            egg_id=egg_id,
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
            allocation_additional=extra_ids or None,
            consuming_order_id=consuming_order_id,
            expiration_date=expiration_date,
            plan_id=plan_id,
            is_trial=is_trial,
        )
        if on_db_created is not None:
            await on_db_created(db, created)
        # 必须先提交，Wings 才能通过 /api/remote/servers/{uuid} 回拉配置。
        await db.commit()

        try:
            await self._runtime.create_server(db, node_id, created.uuid, start_on_completion=start_on_completion)
        except RuntimeAdapterError as create_exc:
            # 计费防双容器补偿：仅当 Wings 确认节点无残留（含 404）才删行恢复强预留，失联则保行供同 UUID 重试。
            node_confirmed_clean = not confirm_clean_on_runtime_failure
            if confirm_clean_on_runtime_failure:
                try:
                    await self._runtime.delete_server(db, node_id, created.uuid)
                    node_confirmed_clean = True
                except RuntimeAdapterError as cleanup_exc:
                    logger.warning(
                        "Wings delete_server compensation unconfirmed for server %s (%s): %s; keeping row",
                        created.id, created.uuid, cleanup_exc,
                    )
            if node_confirmed_clean:
                try:
                    await self.delete_server_row(db, created.id)
                    if restore_order_reservations_on_failure and consuming_order_id is not None:
                        await restore_order_strong_reservations(db, consuming_order_id, [primary_id, *extra_ids])
                    if on_db_compensated is not None:
                        await on_db_compensated(db, created)
                    await db.commit()
                except Exception:  # noqa: BLE001
                    await db.rollback()
                    logger.exception("Failed to compensate DB rollback for server %s", created.id)
            raise ServerRuntimeSyncError(
                f"Wings 创建失败: {create_exc}",
                params={"server_id": created.id, "node_confirmed_clean": node_confirmed_clean},
            ) from create_exc

        # 仅在 Wings 确认开服成功后才永久置位，避免建服失败误耗用户首购试用资格。
        if await mark_user_owned_server(db, owner_id):
            await db.commit()

        created.warnings = await hooks.on_provisioned(
            db, server_id=created.id, user_id=owner_id, plan_snapshot=plan_snapshot
        )
        return created

    async def renew_server(
        self,
        db: AsyncSession,
        server_id: int,
        *,
        new_expiration_date: date | None,
        auto_unsuspend: bool = True,
        convert_plan_id: int | None = None,
        convert_build: ServerBuildPatch | None = None,
        convert_plan_snapshot: Mapping[str, Any] | None = None,
        sync_llm: bool = True,
        actor: str = "system",
    ) -> RenewResult:
        server = await self._get_server_or_404(db, server_id, for_update=True)
        prev_expiration_date = server.expiration_date
        was_suspended = server.is_suspended
        target_plan: BillingPlan | None = None
        if convert_plan_id is not None:
            target_plan = await db.get(BillingPlan, convert_plan_id)
            if target_plan is None:
                await db.rollback()
                raise ServerValidationError(f"套餐 {convert_plan_id} 不存在")

        snapshot = self._snapshot_build_and_plan(server)
        server.expiration_date = new_expiration_date
        server.updated_at = utc_naive_now_sec()
        if convert_plan_id is not None:
            server.plan_id = convert_plan_id
            server.is_trial = False
            if convert_build is not None:
                for field_name, val in self._build_fields_from_patch(convert_build).items():
                    setattr(server, field_name, val)

        await self._commit_and_sync_build_plan(
            db, server, snapshot=snapshot, sync_runtime=(convert_plan_id is not None and convert_build is not None)
        )

        warnings: list[str] = []
        unsuspended = False
        if auto_unsuspend and new_expiration_date is not None and was_suspended:
            unsuspended = True
            warnings.extend((await self.unsuspend_server(db, server_id, actor=actor)).warnings)

        if sync_llm and convert_plan_id is not None:
            effective_snap: Mapping[str, Any] | None = convert_plan_snapshot
            if effective_snap is None and target_plan is not None:
                effective_snap = build_plan_snapshot(target_plan)
            warnings.extend(await hooks.on_plan_changed(db, server_id=server_id, new_snapshot=effective_snap))

        return RenewResult(
            server_id=server_id,
            prev_expiration_date=prev_expiration_date,
            new_expiration_date=new_expiration_date,
            unsuspended=unsuspended,
            converted=convert_plan_id is not None,
            warnings=warnings,
        )

    async def update_build(
        self,
        db: AsyncSession,
        server_id: int,
        patch: ServerBuildPatch | None = None,
        *,
        memory: int | None = None,
        swap: int | None = None,
        disk: int | None = None,
        io: int | None = None,
        cpu: int | None = None,
        allocation_limit: int | None = None,
        database_limit: int | None = None,
        backup_limit: int | None = None,
        threads: str | None = None,
        update_threads: bool = False,
        oom_disabled: bool | None = None,
    ) -> MutationResult:
        effective_patch = patch or ServerBuildPatch(
            memory=memory,
            swap=swap,
            disk=disk,
            io=io,
            cpu=cpu,
            allocation_limit=allocation_limit,
            database_limit=database_limit,
            backup_limit=backup_limit,
            threads=threads,
            update_threads=update_threads,
            oom_disabled=oom_disabled,
        )
        server = await self._get_server_or_404(db, server_id, for_update=True)
        snapshot = self._snapshot_build_and_plan(server)
        for field_name, val in self._build_fields_from_patch(effective_patch).items():
            setattr(server, field_name, val)
        server.updated_at = utc_naive_now_sec()
        await self._commit_and_sync_build_plan(db, server, snapshot=snapshot, sync_runtime=True)
        return MutationResult(server_id=server_id)

    async def apply_plan_transition(
        self,
        db: AsyncSession,
        server_id: int,
        *,
        new_plan_id: int | None,
        build_patch: ServerBuildPatch | None = None,
        new_expiration_date: date | None = None,
        update_expiration: bool = False,
        clear_trial: bool = False,
        new_plan_snapshot: Mapping[str, Any] | None = None,
        sync_llm: bool = True,
        auto_unsuspend: bool = False,
        actor: str = "system",
    ) -> MutationResult:
        target_plan: BillingPlan | None = None
        if new_plan_id is not None:
            target_plan = await db.get(BillingPlan, new_plan_id)
            if target_plan is None:
                raise ServerValidationError("套餐不存在")

        server = await self._get_server_or_404(db, server_id, for_update=True)
        was_suspended = server.is_suspended
        snapshot = self._snapshot_build_and_plan(server)

        server.plan_id = new_plan_id
        if clear_trial:
            server.is_trial = False
        if update_expiration:
            server.expiration_date = new_expiration_date
        if build_patch is not None:
            for field_name, val in self._build_fields_from_patch(build_patch).items():
                setattr(server, field_name, val)
        server.updated_at = utc_naive_now_sec()
        await self._commit_and_sync_build_plan(db, server, snapshot=snapshot, sync_runtime=build_patch is not None)

        warnings: list[str] = []
        if auto_unsuspend and was_suspended:
            warnings.extend((await self.unsuspend_server(db, server_id, actor=actor)).warnings)
        if sync_llm:
            effective_snap: Mapping[str, Any] | None = new_plan_snapshot
            if effective_snap is None and target_plan is not None:
                effective_snap = build_plan_snapshot(target_plan)
            warnings.extend(await hooks.on_plan_changed(db, server_id=server_id, new_snapshot=effective_snap))
        return MutationResult(server_id=server_id, warnings=warnings)

    async def _set_suspended(
        self, db: AsyncSession, server_id: int, *, suspended: bool, actor: str
    ) -> MutationResult:
        server = await self._get_server_or_404(db, server_id, for_update=True)
        prev_status = server.status
        node_id, server_uuid = int(server.node_id), server.uuid
        server.status = "suspended" if suspended else None
        server.updated_at = utc_naive_now_sec()
        await db.commit()
        try:
            await self._runtime.sync_server(db, node_id, server_uuid)
        except RuntimeAdapterError as exc:
            try:
                await db.execute(
                    update(PteroServer)
                    .where(PteroServer.id == server_id)
                    .values(status=prev_status, updated_at=utc_naive_now_sec())
                )
                await db.commit()
            except Exception:  # noqa: BLE001
                logger.exception("Failed to compensate suspend toggle rollback for server %s", server_id)
            raise ServerRuntimeSyncError(f"Wings sync 失败: {exc}") from exc

        hook = hooks.on_suspended if suspended else hooks.on_unsuspended
        return MutationResult(server_id=server_id, warnings=await hook(db, server_id=server_id, actor=actor))

    async def suspend_server(self, db: AsyncSession, server_id: int, *, actor: str = "system") -> MutationResult:
        return await self._set_suspended(db, server_id, suspended=True, actor=actor)

    async def unsuspend_server(self, db: AsyncSession, server_id: int, *, actor: str = "system") -> MutationResult:
        return await self._set_suspended(db, server_id, suspended=False, actor=actor)

    async def reinstall_server(
        self, db: AsyncSession, server_id: int, *, force: bool = False, forbid_suspended: bool = False
    ) -> MutationResult:
        server = await self._get_server_or_404(db, server_id, for_update=True)
        if forbid_suspended and server.is_suspended:
            await db.rollback()
            raise ServerForbiddenError("服务器已冻结，无法重装", code="server.suspended")
        if server.status == "installing":
            await db.rollback()
            raise ServerConflictError("服务器正在安装中", code="server.installing")

        prev_status, prev_installed_at = server.status, server.installed_at
        node_id, server_uuid = int(server.node_id), server.uuid
        server.status = "installing"
        server.installed_at = None
        server.updated_at = utc_naive_now_sec()
        await db.commit()

        try:
            await self._runtime.reinstall_server(db, node_id, server_uuid, force=force)
        except RuntimeAdapterError as exc:
            try:
                await db.execute(
                    update(PteroServer)
                    .where(PteroServer.id == server_id)
                    .values(status=prev_status, installed_at=prev_installed_at, updated_at=utc_naive_now_sec())
                )
                await db.commit()
            except Exception:  # noqa: BLE001
                logger.exception("Failed to compensate reinstall rollback for server %s", server_id)
            raise ServerRuntimeSyncError(f"Wings reinstall 失败: {exc}") from exc
        return MutationResult(server_id=server_id)

    async def delete_server(self, db: AsyncSession, server_id: int, *, force: bool = False) -> DeleteResult:
        row = (
            await db.execute(select(PteroServer.uuid, PteroServer.node_id).where(PteroServer.id == server_id))
        ).first()
        if row is None:
            return DeleteResult(server_id=server_id, existed=False, forced=force)

        server_uuid, node_id = str(row[0]), int(row[1])
        warnings: list[str] = []

        # 先删 Wings 备份与容器，非 force 失败直接中止，避免节点失联时误删用户的 Tunnel 与 LLM 密钥。
        backups = list((await db.execute(select(Backup).where(Backup.server_id == server_id))).scalars().all())
        for backup in backups:
            try:
                await self._runtime.delete_backup(db, node_id, server_uuid, str(backup.uuid))
            except RuntimeAdapterError as exc:
                logger.warning("Wings delete_backup failed for server %s backup %s: %s", server_id, backup.uuid, exc)
                warnings.append(f"节点备份 {backup.uuid} 删除失败: {str(exc)[:150]}")

        try:
            await self._runtime.delete_server(db, node_id, server_uuid)
        except RuntimeAdapterError as exc:
            if not force:
                raise ServerRuntimeSyncError(f"Wings 删除失败: {exc}") from exc
            logger.warning("Forced delete continues after Wings delete failed for server %s: %s", server_id, exc)
            warnings.append(f"强制删除跳过节点容器清理失败: {str(exc)[:200]}")

        warnings.extend(await hooks.on_deleted(db, server_id=server_id))
        await self.delete_server_row(db, server_id)
        await db.commit()
        return DeleteResult(server_id=server_id, existed=True, forced=force, warnings=warnings)

    async def add_allocations(self, db: AsyncSession, server_id: int, *, allocation_ids: list[int]) -> MutationResult:
        server = await self._get_server_or_404(db, server_id)
        unique_ids = list(dict.fromkeys(int(item) for item in allocation_ids))
        now = utc_naive_now_sec()
        allocations = await self._lock_and_validate_allocations(db, server, unique_ids, now)
        snapshot = await self._allocation_snapshot(db, server, unique_ids)
        for alloc in allocations:
            alloc.server_id = server_id
            alloc.reserved_order_id = None
            alloc.reserved_until = None
            alloc.updated_at = now
        server.updated_at = now
        await db.flush()
        await self._commit_then_sync_server(db, server, snapshot=snapshot)
        return MutationResult(server_id=server_id)

    async def remove_allocation(self, db: AsyncSession, server_id: int, allocation_id: int) -> MutationResult:
        server = await self._get_server_or_404(db, server_id)
        if int(server.allocation_id) == int(allocation_id):
            raise ServerValidationError("不能移除主分配，请先切换主分配")
        allocation = (
            await db.execute(
                select(Allocation)
                .where(Allocation.id == allocation_id)
                .order_by(Allocation.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if allocation is None or allocation.server_id != server_id:
            await db.rollback()
            raise ServerValidationError(f"分配 {allocation_id} 不属于该服务器")

        now = utc_naive_now_sec()
        snapshot = await self._allocation_snapshot(db, server, [allocation_id])
        allocation.server_id = None
        allocation.notes = None
        allocation.updated_at = now
        server.updated_at = now
        await db.flush()
        await self._commit_then_sync_server(db, server, snapshot=snapshot)
        return MutationResult(server_id=server_id)

    async def set_primary_allocation(self, db: AsyncSession, server_id: int, allocation_id: int) -> MutationResult:
        server = await self._get_server_or_404(db, server_id)
        now = utc_naive_now_sec()
        (allocation,) = await self._lock_and_validate_allocations(db, server, [allocation_id], now)
        new_port = int(allocation.port)
        snapshot = await self._allocation_snapshot(db, server, [allocation_id])
        allocation.server_id = server_id
        allocation.reserved_order_id = None
        allocation.reserved_until = None
        allocation.updated_at = now
        server.allocation_id = allocation_id
        server.updated_at = now
        await db.flush()
        await self._commit_then_sync_server(db, server, snapshot=snapshot)
        warnings = await hooks.on_primary_allocation_changed(db, server_id=server_id, new_port=new_port)
        return MutationResult(server_id=server_id, warnings=warnings)

    async def update_details(
        self,
        db: AsyncSession,
        server_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        external_id: str | None = None,
        provided: set[str],
    ) -> MutationResult:
        server = await self._get_server_or_404(db, server_id)
        if "name" in provided:
            value = (name or "").strip()
            if not value:
                raise ServerValidationError("服务器名称不能为空")
            server.name = value
        if "description" in provided:
            server.description = description or ""
        if "external_id" in provided or "externalId" in provided:
            server.external_id = (external_id or "").strip() or None
        server.updated_at = utc_naive_now_sec()
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ServerValidationError("external_id 已被占用") from exc
        return MutationResult(server_id=server_id)

    async def update_owner(self, db: AsyncSession, server_id: int, *, owner_id: int) -> MutationResult:
        server = await self._get_server_or_404(db, server_id)
        old_owner_uuid = server.owner.uuid
        if await db.get(PteroUser, owner_id) is None:
            raise ServerValidationError(f"用户 {owner_id} 不存在")
        if int(server.owner_id) == owner_id:
            return MutationResult(server_id=server_id)

        node_id, server_uuid = int(server.node_id), server.uuid
        server.owner_id = owner_id
        server.updated_at = utc_naive_now_sec()
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ServerValidationError("服务器所有者更新失败") from exc

        warnings: list[str] = []
        try:
            await self._runtime.deauthorize_user(db, node_id, old_owner_uuid, server_uuids=[server_uuid])
        except RuntimeAdapterError as exc:
            logger.warning("Failed to deauthorize old owner %s for server %s: %s", old_owner_uuid, server_id, exc)
            warnings.append("服务器所有者已更新，但旧所有者的 Wings 会话撤销失败")
        return MutationResult(server_id=server_id, warnings=warnings)

    async def update_startup(
        self,
        db: AsyncSession,
        server_id: int,
        *,
        image: str | None = None,
        startup: str | None = None,
        skip_scripts: bool | None = None,
        provided: set[str],
    ) -> MutationResult:
        server = await self._get_server_or_404(db, server_id)
        snapshot = await self._server_config_snapshot(db, server)
        if "image" in provided:
            value = (image or "").strip()
            if not value:
                raise ServerValidationError("Docker 镜像不能为空")
            server.image = value
        if "startup" in provided:
            value = (startup or "").strip()
            if not value:
                raise ServerValidationError("启动命令不能为空")
            server.startup = value
        if "skip_scripts" in provided or "skipScripts" in provided:
            server.skip_scripts = bool(skip_scripts)
        server.updated_at = utc_naive_now_sec()
        await db.flush()
        await self._commit_then_sync_server(db, server, snapshot=snapshot, restore_kind="server_config")
        return MutationResult(server_id=server_id)

    async def switch_egg(
        self,
        db: AsyncSession,
        server_id: int,
        *,
        egg_id: int,
        environment: dict[str, str],
        image: str | None = None,
        startup: str | None = None,
        skip_scripts: bool | None = None,
        provided: set[str],
    ) -> MutationResult:
        server = await self._get_server_or_404(db, server_id)
        snapshot = await self._server_config_snapshot(db, server)
        egg = await db.get(Egg, egg_id)
        if egg is None:
            raise ServerValidationError(f"Egg {egg_id} 不存在")

        egg_variables = list(
            (await db.execute(select(EggVariable).where(EggVariable.egg_id == egg_id).order_by(EggVariable.id.asc())))
            .scalars()
            .all()
        )
        values: dict[int, str] = {}
        for variable in egg_variables:
            val = str(environment.get(variable.env_variable, variable.default_value))
            try:
                validate_environment(variable.env_variable, val, variable.rules)
            except EggValidationError as exc:
                raise ServerValidationError(str(exc)) from exc
            values[int(variable.id)] = val

        now = utc_naive_now_sec()
        server.nest_id = egg.nest_id
        server.egg_id = int(egg_id)
        if "image" in provided:
            value = (image or "").strip()
            if not value:
                raise ServerValidationError("Docker 镜像不能为空")
            server.image = value
        if "startup" in provided:
            value = (startup or "").strip()
            if not value:
                raise ServerValidationError("启动命令不能为空")
            server.startup = value
        if "skip_scripts" in provided or "skipScripts" in provided:
            server.skip_scripts = bool(skip_scripts)
        server.updated_at = now

        await db.execute(sql_delete(ServerVariable).where(ServerVariable.server_id == server_id))
        for variable in egg_variables:
            db.add(
                ServerVariable(
                    server_id=server_id,
                    variable_id=int(variable.id),
                    variable_value=values[int(variable.id)],
                    created_at=now,
                    updated_at=now,
                )
            )
        await db.flush()
        await self._commit_then_sync_server(db, server, snapshot=snapshot, restore_kind="server_config")
        return MutationResult(server_id=server_id)

    async def update_variables(
        self,
        db: AsyncSession,
        server_id: int,
        *,
        variables: dict[str, str],
        user_editable_only: bool = False,
        sync_runtime: bool = True,
    ) -> VariablesUpdateResult:
        server = await self._get_server_or_404(db, server_id)
        snapshot = await self._server_config_snapshot(db, server)
        egg_variables = {
            v.env_variable: v
            for v in (await db.execute(select(EggVariable).where(EggVariable.egg_id == server.egg_id))).scalars().all()
        }
        if not user_editable_only:
            unknown = sorted(set(variables) - set(egg_variables))
            if unknown:
                raise ServerValidationError(f"未知变量: {', '.join(unknown)}")

        existing = {
            int(sv.variable_id): sv
            for sv in (await db.execute(select(ServerVariable).where(ServerVariable.server_id == server_id)))
            .scalars()
            .all()
        }
        egg_name = server.egg.name if server.egg else None
        now = utc_naive_now_sec()
        changes: list[VariableChange] = []

        for env_name, raw_value in variables.items():
            value = "" if raw_value is None else str(raw_value)
            if user_editable_only:
                err = validate_startup_variable(egg_name, env_name, value)
                if err:
                    raise ServerValidationError(
                        err, code="server.startup_variable_invalid", params={"variable": env_name}
                    )
                egg_variable = egg_variables.get(env_name)
                if egg_variable is None or not egg_variable.user_editable:
                    continue
            else:
                egg_variable = egg_variables[env_name]
                try:
                    validate_environment(egg_variable.env_variable, value, egg_variable.rules)
                except EggValidationError as exc:
                    raise ServerValidationError(str(exc)) from exc

            sv = existing.get(int(egg_variable.id))
            old_value = sv.variable_value if sv is not None and sv.variable_value is not None else egg_variable.default_value
            if sv is None:
                db.add(
                    ServerVariable(
                        server_id=server_id,
                        variable_id=int(egg_variable.id),
                        variable_value=value,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                sv.variable_value = value
                sv.updated_at = now
            changes.append(
                VariableChange(
                    variable_id=int(egg_variable.id),
                    env_variable=egg_variable.env_variable,
                    old_value=old_value,
                    new_value=value,
                )
            )

        if user_editable_only and not any(c.changed for c in changes):
            await db.commit()
            return VariablesUpdateResult(server_id=server_id, changes=changes)

        server.updated_at = now
        await db.flush()
        if sync_runtime:
            await self._commit_then_sync_server(db, server, snapshot=snapshot, restore_kind="server_config")
        else:
            await db.commit()
        return VariablesUpdateResult(server_id=server_id, changes=changes)

    async def on_install_completed(
        self,
        db: AsyncSession,
        *,
        server_uuid: str,
        node_id: int,
        successful: bool,
        reinstall: bool = False,
    ) -> InstallCompletedResult:
        # 结束 require_wings_node 开启的只读快照，避免 MariaDB 11.8 REPEATABLE READ 下 FOR UPDATE 撞 ER_CHECKREAD(1020)。
        await db.commit()

        server_id_val = 0
        final_status: str | None = None
        first_install_notified = False
        no_email_owner_id: int | None = None

        for attempt in range(5):
            no_email_owner_id = None
            first_install_notified = False
            try:
                server = (
                    await db.execute(
                        select(PteroServer)
                        .where(or_(PteroServer.uuid == server_uuid, PteroServer.uuid_short == server_uuid))
                        .options(noload("*"))
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).scalar_one_or_none()
                if server is None:
                    raise ServerNotFoundError(f"服务器 {server_uuid} 不存在")
                if int(server.node_id) != int(node_id):
                    raise ServerForbiddenError("Requesting node does not have permission to access this server.")

                new_status: str | None = None if successful else ("reinstall_failed" if reinstall else "install_failed")
                if server.status == "suspended":
                    new_status = "suspended"

                now = utc_naive_now()
                server.status = new_status
                server.installed_at = now
                server.updated_at = now

                # 仅以 install_notified_at 判首次成功通知，兼容初装失败后重装成功的补发。
                if successful and new_status is None and server.install_notified_at is None:
                    try:
                        async with db.begin_nested():
                            server.install_notified_at = now
                            await db.flush()

                            from app.services.notifications.policy import load_policy
                            from app.services.notifications.queue import enqueue_user_email

                            if (await load_policy(db)).lifecycle.installed:
                                owner = await db.get(PteroUser, server.owner_id)
                                email = (owner.email or "").strip() if owner is not None else ""
                                if not email:
                                    no_email_owner_id = int(server.owner_id)
                                else:
                                    username = (owner.username or "") if owner is not None else ""
                                    tz_name = await get_runtime_timezone(db)
                                    await enqueue_user_email(
                                        db,
                                        event_key=f"server_installed:{server.id}",
                                        recipient=email,
                                        subject=f"服务器 {server.name} 已开通",
                                        template="server_installed",
                                        variables={
                                            "username": username,
                                            "server_name": server.name or "",
                                            "server_id": int(server.id),
                                            "server_uuid": server.uuid or "",
                                            "installed_at": format_in_timezone(now, tz_name) or "",
                                        },
                                        greeting=f"您好, {username}!" if username else "您好!",
                                        action_text="进入控制台",
                                        path=f"/servers/{server.id}/console",
                                        topic=f"server_installed:{server.id}",
                                        context={
                                            "lifecycle_key": "installed",
                                            "audit_source": "server_install_notify",
                                            "server_id": int(server.id),
                                            "owner_id": int(server.owner_id),
                                        },
                                    )
                                    first_install_notified = True
                    except OperationalError:
                        raise
                    except Exception:
                        server.install_notified_at = None
                        logger.warning(
                            "server_engine: failed to enqueue install notification for server %s",
                            server.id,
                            exc_info=True,
                        )

                server_id_val = int(server.id)
                final_status = new_status
                await db.commit()
                break
            except OperationalError as exc:
                await db.rollback()
                if _is_retryable_lock_error(exc) and attempt < 4:
                    continue
                raise

        if no_email_owner_id is not None:
            from app.services.audit import log_manager_activity

            await log_manager_activity(
                db,
                actor="system",
                category="automation",
                operation=OperationResult(
                    action="automation.install_notify",
                    phase="request",
                    outcome="failed",
                    target={"server_id": server_id_val, "owner_id": no_email_owner_id},
                ),
                detail_key="install_notify.no_email",
                detail_params={"server_id": server_id_val, "owner_id": no_email_owner_id},
            )

        return InstallCompletedResult(
            server_id=server_id_val,
            status=final_status,
            first_install_notified=first_install_notified,
            no_email_owner_id=no_email_owner_id,
        )


server_engine = ServerLifecycleEngine()

__all__ = ["ServerLifecycleEngine", "server_engine"]
