from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.db.models.billing import BillingPlan


@dataclass(slots=True)
class CreatedServer:
    id: int
    uuid: str
    uuid_short: str
    name: str
    owner_id: int
    node_id: int
    allocation_id: int
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ServerBuildPatch:
    memory: int | None = None
    swap: int | None = None
    disk: int | None = None
    io: int | None = None
    cpu: int | None = None
    allocation_limit: int | None = None
    database_limit: int | None = None
    backup_limit: int | None = None
    threads: str | None = None
    update_threads: bool = False
    oom_disabled: bool | None = None

    @classmethod
    def from_plan(cls, plan: BillingPlan) -> ServerBuildPatch:
        return cls(
            cpu=int(plan.cpu),
            memory=int(plan.memory_mb),
            disk=int(plan.disk_mb),
            swap=int(plan.swap_mb),
            io=int(plan.io),
            database_limit=int(plan.database_limit),
            backup_limit=int(plan.backup_limit),
            allocation_limit=int(plan.allocation_limit),
            oom_disabled=bool(plan.oom_disabled),
        )

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> ServerBuildPatch:
        def _opt_int(key: str) -> int | None:
            val = snapshot.get(key)
            return int(val) if val is not None else None

        oom = snapshot.get("oom_disabled")
        return cls(
            cpu=_opt_int("cpu"),
            memory=_opt_int("memory_mb"),
            disk=_opt_int("disk_mb"),
            swap=_opt_int("swap_mb"),
            io=_opt_int("io"),
            database_limit=_opt_int("database_limit"),
            backup_limit=_opt_int("backup_limit"),
            allocation_limit=_opt_int("allocation_limit"),
            oom_disabled=bool(oom) if oom is not None else None,
        )


@dataclass(slots=True)
class MutationResult:
    server_id: int
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RenewResult:
    server_id: int
    prev_expiration_date: date | None
    new_expiration_date: date | None
    unsuspended: bool = False
    converted: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DeleteResult:
    server_id: int
    existed: bool = True
    forced: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class VariableChange:
    variable_id: int
    env_variable: str
    old_value: str
    new_value: str

    @property
    def changed(self) -> bool:
        return self.old_value != self.new_value


@dataclass(slots=True)
class VariablesUpdateResult:
    server_id: int
    changes: list[VariableChange] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class InstallCompletedResult:
    server_id: int
    status: str | None
    first_install_notified: bool = False
    no_email_owner_id: int | None = None
    warnings: list[str] = field(default_factory=list)


__all__ = [
    "CreatedServer",
    "ServerBuildPatch",
    "MutationResult",
    "RenewResult",
    "DeleteResult",
    "VariableChange",
    "VariablesUpdateResult",
    "InstallCompletedResult",
]
