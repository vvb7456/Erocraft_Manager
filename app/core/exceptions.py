"""Exception handlers shared by the FastAPI app."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from starlette.exceptions import HTTPException

from app.core.api_errors import ApiError, HTTP_ERROR_CODES, problem_response
from app.core.contracts import ErrorInfo
from app.services.agent_client import AgentClientError

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AgentClientError)
    async def agent_error_handler(request: Request, exc: AgentClientError) -> JSONResponse:
        return problem_response(504 if exc.error.code == "dependency.timeout" else 502, exc.error, request=request)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc, ApiError):
            return problem_response(
                exc.status_code, exc.error, request=request, headers=exc.headers,
                operation=exc.operation, context=exc.context,
            )
        detail: Any = exc.detail
        return problem_response(
            exc.status_code,
            ErrorInfo(code=HTTP_ERROR_CODES.get(exc.status_code, "request.invalid"), detail=detail if isinstance(detail, str) else None),
            request=request, headers=exc.headers,
            context=detail if isinstance(detail, dict) else None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        malformed = any(error["type"] == "json_invalid" for error in errors)
        fields = [
            {"location": error["loc"][0], "path": list(error["loc"][1:]),
             "code": "validation.required" if error["type"] == "missing" else "validation.invalid"}
            for error in errors if error["loc"]
        ]
        return problem_response(
            400 if malformed else 422,
            ErrorInfo(code="request.malformed_json" if malformed else "request.validation_failed"),
            request=request, fields=fields,
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        original = _rate_limit_exceeded_handler(request, exc)
        headers = {key: value for key, value in original.headers.items() if key not in {"content-type", "content-length"}}
        return problem_response(429, ErrorInfo(code="request.rate_limited"), request=request, headers=headers)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception in FastAPI app", exc_info=exc)
        return problem_response(500, ErrorInfo(code="system.internal_error"), request=request)
