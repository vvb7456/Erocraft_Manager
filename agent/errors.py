"""HTTP errors at the Agent boundary; command execution results use the RPC model."""

from __future__ import annotations

from typing import Dict, Mapping, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .contracts import ErrorInfo, OperationResult
from .error_codes import ERROR_TITLES, ErrorCode


def register_error_handlers(app: FastAPI) -> None:
    def response(request: Request, status: int, code: ErrorCode, headers: Optional[Mapping[str, str]] = None) -> JSONResponse:
        error = ErrorInfo(code=code)
        operation = OperationResult(action="agent.http_request", phase="request", outcome="failed", error=error)
        response_headers = dict(headers or {})
        if status == 401:
            response_headers.setdefault("WWW-Authenticate", "Bearer")
        return JSONResponse({
            "type": f"tag:erocraft.com,2026-10-15:error:{code}", "title": ERROR_TITLES[code],
            "status": status, "code": code,
            "operation": operation.model_dump(exclude_none=True, exclude_defaults=True),
        }, status_code=status, headers=response_headers, media_type="application/problem+json")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        codes: Dict[int, ErrorCode] = {401: "auth.invalid_token", 403: "auth.forbidden", 404: "resource.not_found", 405: "request.method_not_allowed", 503: "system.unavailable"}
        return response(request, exc.status_code, codes.get(exc.status_code, "request.invalid"), exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        malformed = any(error["type"] == "json_invalid" for error in exc.errors())
        return response(request, 400 if malformed else 422, "request.malformed_json" if malformed else "request.validation_failed")

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception) -> JSONResponse:
        import logging
        logging.getLogger(__name__).exception("Agent HTTP request failed", exc_info=exc)
        return response(request, 500, "system.internal_error")
