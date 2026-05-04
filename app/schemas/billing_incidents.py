"""Incident schemas — see ``docs/BILLING_DESIGN.md`` §11.1."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Forbid(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IncidentOut(BaseModel):
    """``manager_billing_incidents`` row projection."""

    id: int
    kind: str
    order_id: int | None
    invoice_id: int | None
    transaction_id: int | None
    server_id: int | None
    payload: dict[str, Any]
    detected_at: str
    status: str
    resolution_note: str | None
    resolved_by: int | None
    resolved_at: str | None


class IncidentUpdateRequest(_Forbid):
    """``PATCH /api/admin/billing/incidents/:id`` — §11.1.

    All fields optional; at least one must be present (validated by router).
    """

    status: str | None = Field(
        default=None,
        pattern=r"^(open|investigating|resolved|wontfix)$",
    )
    resolution_note: str | None = Field(default=None, max_length=1000)
