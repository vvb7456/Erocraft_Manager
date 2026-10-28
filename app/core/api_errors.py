"""HTTP boundary for structured errors; business services keep their own exceptions."""

from __future__ import annotations

from typing import Any
from collections.abc import Mapping

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.contracts import ErrorInfo, OperationResult
from app.core.error_codes import ERROR_TITLES, ErrorCode

HTTP_ERROR_CODES: dict[int, ErrorCode] = {
    400: "request.invalid", 401: "auth.invalid_token", 403: "auth.forbidden",
    404: "resource.not_found", 405: "request.method_not_allowed", 409: "resource.conflict", 410: "resource.not_found",
    413: "request.too_large", 415: "request.unsupported_media_type", 422: "request.validation_failed",
    429: "request.rate_limited", 500: "system.internal_error", 501: "system.unsupported",
    502: "dependency.failed", 503: "system.unavailable", 504: "dependency.timeout",
}


class ApiError(HTTPException):
    def __init__(
        self, status_code: int, code: ErrorCode, *, detail: str | None = None,
        params: dict[str, str | int | float | bool] | None = None,
        headers: dict[str, str] | None = None, operation: OperationResult | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(status_code, detail=detail, headers=headers)
        self.error = ErrorInfo(code=code, detail=detail, params=params or {})
        self.operation = operation
        self.context = context


def problem_response(
    status: int, error: ErrorInfo, *, request: Request | None = None,
    headers: Mapping[str, str] | None = None, operation: OperationResult | None = None,
    fields: list[dict[str, Any]] | None = None, context: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"tag:erocraft.com,2026-10-15:error:{error.code}",
        "title": ERROR_TITLES[error.code], "status": status,
        **error.model_dump(exclude_none=True, exclude_defaults=True),
    }
    if fields:
        body["fields"] = fields
    if context:
        body["context"] = context
    request_context = getattr(request.state, "operation", None) if request else None
    if operation is None and request_context is not None:
        operation = request_context.result or request_context.request_result(status, error)
    if operation is not None:
        body["operation"] = operation.model_dump(exclude_none=True, exclude_defaults=True)
        if request_context is not None:
            request_context.result = operation
    response_headers = dict(headers or {})
    if status == 401:
        response_headers.setdefault("WWW-Authenticate", 'Session realm="manager"')
    return JSONResponse(body, status_code=status, headers=response_headers, media_type="application/problem+json")
