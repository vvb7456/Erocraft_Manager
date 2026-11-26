from __future__ import annotations

from typing import Any


class ServerEngineError(RuntimeError):
    default_status_code: int = 500
    default_code: str | None = None

    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = self.default_status_code if status_code is None else status_code
        self.code = self.default_code if code is None else code
        self.params = params


class ServerNotFoundError(ServerEngineError):
    default_status_code = 404
    default_code = "resource.not_found"


class ServerValidationError(ServerEngineError):
    default_status_code = 422
    default_code = "request.validation_failed"


class ServerForbiddenError(ServerEngineError):
    default_status_code = 403
    default_code = "auth.forbidden"


class ServerConflictError(ServerEngineError):
    default_status_code = 409
    default_code = "resource.conflict"


class ServerRuntimeSyncError(ServerEngineError):
    default_status_code = 502
    default_code = "dependency.failed"


__all__ = [
    "ServerEngineError",
    "ServerNotFoundError",
    "ServerValidationError",
    "ServerForbiddenError",
    "ServerConflictError",
    "ServerRuntimeSyncError",
]
