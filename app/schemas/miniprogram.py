"""Account-owned summaries and authentication for the native console."""

from typing import Literal

from pydantic import BaseModel, Field

from app.core.contracts import OperationResult
from app.schemas.auth import LoginRequest


class MiniLoginInput(BaseModel):
    code: str = Field(min_length=1, max_length=256)


class MiniBindInput(LoginRequest):
    username: str = Field(min_length=1, max_length=191)
    password: str = Field(min_length=1, max_length=72)


class MiniUser(BaseModel):
    id: int
    username: str


class MiniLoginOut(BaseModel):
    token: str
    expires_at: str
    user: MiniUser | None = None
    operation: OperationResult


class MiniServer(BaseModel):
    id: int
    name: str
    status: str | None
    suspended: bool
    installing: bool
    expires_on: str | None
    node: str


class MiniServerStatus(BaseModel):
    state: Literal["running", "offline", "starting", "stopping"]
    suspended: bool


class MiniOrder(BaseModel):
    id: int
    order_no: str
    title: str
    kind: str
    status: str
    total_fen: int
    received_fen: int
    refunded_fen: int
    total_days: int
    currency: str
    created_at: str
    applied_at: str | None


class MiniOrders(BaseModel):
    items: list[MiniOrder]
    has_more: bool
