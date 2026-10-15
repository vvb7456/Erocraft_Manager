"""Wire models shared by Manager and Agent; copied into each deployment package."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .error_codes import ErrorCode


class ErrorInfo(BaseModel):
    code: ErrorCode
    detail: str | None = None
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)


class OperationResult(BaseModel):
    action: str
    phase: Literal["request", "execution", "observation", "acceptance"]
    outcome: Literal["success", "failed"]
    target: dict[str, str | int | list[int]] = Field(default_factory=dict)
    facts: dict[str, str | int | bool] = Field(default_factory=dict)
    error: ErrorInfo | None = None
    succeeded: int | None = None
    failed: int | None = None
    children: list[OperationResult] = Field(default_factory=list)


class FieldError(ErrorInfo):
    location: Literal["body", "query", "path", "header"]
    path: list[str | int]


class ProblemDetails(ErrorInfo):
    type: str
    title: str
    status: int
    fields: list[FieldError] | None = None
    context: dict[str, Any] | None = None
    operation: OperationResult | None = None


class CommandSuccess(BaseModel):
    id: int
    ok: Literal[True] = True
    output: Any = None
    duration_ms: int
    operation: OperationResult


class CommandFailure(BaseModel):
    id: int
    ok: Literal[False] = False
    error: ErrorInfo
    duration_ms: int
    operation: OperationResult
