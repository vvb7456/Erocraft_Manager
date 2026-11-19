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

from app.api.deps.wings_remote_auth import WingsRemoteError
from app.core.api_errors import ApiError, HTTP_ERROR_CODES, problem_response
from app.core.contracts import ErrorInfo
from app.services.agent_client import AgentClientError
from app.services.node_management import AdminResourceError

logger = logging.getLogger(__name__)


def _is_wings_remote_path(request: Request) -> bool:
    return request.url.path.startswith("/api/remote/")


def _pydantic_type_to_laravel_rule(error_type: str, ctx: Any = None) -> str:
    if error_type == "missing":
        return "required"
    # Laravel ConvertEmptyStringsToNull turns "" into null before 'required' validation.
    if error_type == "string_too_short" and isinstance(ctx, dict) and ctx.get("min_length") == 1:
        return "required"
    if error_type in {"literal_error", "enum"}:
        return "in"
    if error_type in {"string_type", "string_too_short", "string_too_long"}:
        return "string"
    if error_type in {"list_type", "too_short"}:
        return "array"
    if error_type.startswith("bool"):
        return "boolean"
    if error_type.startswith(("int", "float")):
        return "numeric"
    if "uuid" in error_type:
        return "uuid"
    if "ip" in error_type:
        return "ip"
    return error_type


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(WingsRemoteError)
    async def wings_remote_error_handler(request: Request, exc: WingsRemoteError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_payload(),
            headers=exc.headers,
        )

    @app.exception_handler(AgentClientError)
    async def agent_error_handler(request: Request, exc: AgentClientError) -> JSONResponse:
        return problem_response(504 if exc.error.code == "dependency.timeout" else 502, exc.error, request=request)

    @app.exception_handler(AdminResourceError)
    async def admin_resource_error_handler(request: Request, exc: AdminResourceError) -> JSONResponse:
        return problem_response(
            exc.status_code,
            ErrorInfo(
                code=HTTP_ERROR_CODES.get(exc.status_code, "request.invalid"),
                detail=exc.detail,
            ),
            request=request,
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        if _is_wings_remote_path(request) and not isinstance(exc, ApiError):
            code = "NotFoundHttpException" if exc.status_code == 404 else "HttpException"
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "errors": [
                        {
                            "code": code,
                            "status": str(exc.status_code),
                            "detail": exc.detail if isinstance(exc.detail, str) else "",
                        }
                    ]
                },
                headers=exc.headers,
            )
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
        if _is_wings_remote_path(request):
            if malformed:
                return JSONResponse(
                    status_code=400,
                    content={
                        "errors": [
                            {
                                "code": "BadRequestHttpException",
                                "status": "400",
                                "detail": "Malformed JSON payload.",
                            }
                        ]
                    },
                )
            remote_errors = [
                {
                    "code": "ValidationException",
                    "status": "422",
                    "detail": str(error.get("msg") or "Validation failed."),
                    "meta": {
                        "source_field": ".".join(str(part) for part in error["loc"][1:])
                        if len(error["loc"]) > 1
                        else "",
                        "rule": _pydantic_type_to_laravel_rule(
                            str(error["type"]),
                            error.get("ctx"),
                        ),
                    },
                }
                for error in errors
            ]
            return JSONResponse(status_code=422, content={"errors": remote_errors})
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
        if _is_wings_remote_path(request):
            return JSONResponse(
                status_code=500,
                content={
                    "errors": [
                        {
                            "code": "HttpException",
                            "status": "500",
                            "detail": "An unexpected error occurred.",
                        }
                    ]
                },
            )
        return problem_response(500, ErrorInfo(code="system.internal_error"), request=request)
