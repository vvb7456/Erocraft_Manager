from __future__ import annotations

from app.services.server_engine import hooks
from app.services.server_engine.engine import ServerLifecycleEngine, server_engine
from app.services.server_engine.errors import (
    ServerConflictError,
    ServerEngineError,
    ServerForbiddenError,
    ServerNotFoundError,
    ServerRuntimeSyncError,
    ServerValidationError,
)
from app.services.server_engine.queries import (
    get_server_detail,
    get_server_or_404,
    get_server_runtime,
    list_available_allocations,
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

__all__ = [
    "ServerLifecycleEngine",
    "server_engine",
    "hooks",
    "ServerEngineError",
    "ServerNotFoundError",
    "ServerValidationError",
    "ServerForbiddenError",
    "ServerConflictError",
    "ServerRuntimeSyncError",
    "CreatedServer",
    "ServerBuildPatch",
    "MutationResult",
    "RenewResult",
    "DeleteResult",
    "VariableChange",
    "VariablesUpdateResult",
    "InstallCompletedResult",
    "get_server_or_404",
    "get_server_detail",
    "get_server_runtime",
    "list_available_allocations",
]
