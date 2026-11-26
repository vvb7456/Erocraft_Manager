from __future__ import annotations

import builtins


class RuntimeError(builtins.RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RuntimeUnreachableError(RuntimeError):
    pass


class RuntimeTimeoutError(RuntimeUnreachableError):
    pass


class RuntimeNotFoundError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = 404) -> None:
        super().__init__(message, status_code=status_code)


class RuntimeConflictError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = 409) -> None:
        super().__init__(message, status_code=status_code)


# 兼容非生命周期调用方（文件、监控、控制台、小程序）对 WingsServiceError 的捕获。
WingsServiceError = RuntimeError

__all__ = [
    "RuntimeError",
    "RuntimeUnreachableError",
    "RuntimeTimeoutError",
    "RuntimeNotFoundError",
    "RuntimeConflictError",
    "WingsServiceError",
]
