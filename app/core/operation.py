"""Request-local business outcomes, independent of response status and audit storage."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.contracts import ErrorInfo, OperationResult


@dataclass
class OperationContext:
    scope: Scope
    result: OperationResult | None = None

    def request_result(self, status: int, error: ErrorInfo | None = None) -> OperationResult:
        endpoint = self.scope.get("endpoint")
        action = (
            f"{endpoint.__module__.rsplit('.', 1)[-1]}.{endpoint.__name__}"
            if endpoint else "http.request"
        )
        return OperationResult(
            action=action, phase="request", outcome="failed" if status >= 400 else "success",
            target=self.scope.get("path_params", {}), error=error,
        )


_current: ContextVar[OperationContext | None] = ContextVar("operation_context", default=None)


def set_operation(result: OperationResult) -> OperationResult:
    context = _current.get()
    if context is not None:
        context.result = result
    return result


def batch_operation(
    action: str, target: dict[str, str | int | list[int]], succeeded: int, failed: int,
) -> OperationResult:
    return set_operation(OperationResult(
        action=action, phase="execution", outcome="failed" if failed else "success",
        target=target, succeeded=succeeded, failed=failed,
    ))


class OperationMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        context = OperationContext(scope)
        scope.setdefault("state", {})["operation"] = context
        token = _current.set(context)

        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)
