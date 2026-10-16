"""Wire models shared by Manager and Agent, including Python 3.8 DSM nodes."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from .error_codes import ErrorCode


class ErrorInfo(BaseModel):
    code: ErrorCode
    detail: Optional[str] = None
    params: Dict[str, Union[str, int, float, bool]] = Field(default_factory=dict)


class OperationResult(BaseModel):
    action: str
    phase: Literal["request", "execution", "observation", "acceptance"]
    outcome: Literal["success", "failed"]
    target: Dict[str, Union[str, int, List[int]]] = Field(default_factory=dict)
    facts: Dict[str, Union[str, int, bool]] = Field(default_factory=dict)
    error: Optional[ErrorInfo] = None
    succeeded: Optional[int] = None
    failed: Optional[int] = None
    children: List[OperationResult] = Field(default_factory=list)


class FieldError(ErrorInfo):
    location: Literal["body", "query", "path", "header"]
    path: List[Union[str, int]]


class ProblemDetails(ErrorInfo):
    type: str
    title: str
    status: int
    fields: Optional[List[FieldError]] = None
    context: Optional[Dict[str, Any]] = None
    operation: Optional[OperationResult] = None


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
