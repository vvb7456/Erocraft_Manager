"""Request-local business outcomes, independent of response status and audit storage."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
import json

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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

        async def send_response(message: Message) -> None:
            if message["type"] == "http.response.start":
                request_result = context.request_result(message["status"])
                scope["state"]["request_result"] = request_result
                result = context.result or request_result
                scope["state"]["operation_result"] = result
                headers = MutableHeaders(scope=message)
                headers["X-Operation-Action"] = result.action
                headers["X-Operation-Phase"] = result.phase
                headers["X-Operation-Outcome"] = result.outcome
                targets = {key: value for key, value in result.target.items() if not isinstance(value, list)}
                if targets:
                    headers["X-Operation-Target"] = json.dumps(targets, separators=(",", ":"))
                if result.succeeded is not None:
                    headers["X-Operation-Succeeded"] = str(result.succeeded)
                if result.failed is not None:
                    headers["X-Operation-Failed"] = str(result.failed)
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        finally:
            _current.reset(token)
