"""Thin compatibility facade re-exporting ``app.services.runtime`` for non-lifecycle callers."""

from __future__ import annotations

from app.services.runtime.errors import (
    RuntimeConflictError,
    RuntimeError,
    RuntimeNotFoundError,
    RuntimeTimeoutError,
    RuntimeUnreachableError,
    WingsServiceError,
)
from app.services.runtime.wings_adapter import (
    RuntimeNodeEndpoint as _NodeInfo,
    WingsRuntimeAdapter as WingsService,
    wings_runtime_adapter as wings_service,
)

__all__ = [
    "WingsService",
    "WingsServiceError",
    "wings_service",
    "RuntimeError",
    "RuntimeUnreachableError",
    "RuntimeTimeoutError",
    "RuntimeNotFoundError",
    "RuntimeConflictError",
    "_NodeInfo",
]
