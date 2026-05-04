"""Admin routes for billing incidents — see ``BILLING_DESIGN.md`` §11.1.

* ``GET   /admin/billing/incidents``           — list (filterable)
* ``PATCH /admin/billing/incidents/{id}``      — update status / note
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.time import to_iso_z, utc_naive_now
from app.db.models.billing import BillingIncident
from app.db.models.pterodactyl import PteroUser
from app.schemas.billing_incidents import IncidentOut, IncidentUpdateRequest
from app.services.audit import log_manager_activity

router = APIRouter(prefix="/admin/billing/incidents", tags=["billing"])


def _serialize(row: BillingIncident) -> IncidentOut:
    return IncidentOut(
        id=row.id,
        kind=row.kind,
        order_id=row.order_id,
        invoice_id=row.invoice_id,
        transaction_id=row.transaction_id,
        server_id=row.server_id,
        payload=row.payload or {},
        detected_at=to_iso_z(row.detected_at),
        status=row.status,
        resolution_note=row.resolution_note,
        resolved_by=row.resolved_by,
        resolved_at=to_iso_z(row.resolved_at) if row.resolved_at else None,
    )


@router.get("", response_model=list[IncidentOut])
async def list_incidents_endpoint(
    status_filter: str | None = Query(
        None,
        alias="status",
        pattern=r"^(open|investigating|resolved|wontfix)$",
    ),
    kind: str | None = Query(None, max_length=64),
    order_id: int | None = Query(None, gt=0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[IncidentOut]:
    stmt = select(BillingIncident).order_by(BillingIncident.id.desc())
    if status_filter:
        stmt = stmt.where(BillingIncident.status == status_filter)
    if kind:
        stmt = stmt.where(BillingIncident.kind == kind)
    if order_id:
        stmt = stmt.where(BillingIncident.order_id == order_id)
    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [_serialize(r) for r in rows]


@router.patch("/{incident_id}", response_model=IncidentOut)
async def update_incident_endpoint(
    incident_id: int,
    payload: IncidentUpdateRequest,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> IncidentOut:
    if payload.status is None and payload.resolution_note is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="至少需要提供 status 或 resolution_note 之一",
        )

    incident = await db.scalar(
        select(BillingIncident).where(BillingIncident.id == incident_id)
    )
    if incident is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="事件不存在")

    now = utc_naive_now()
    changed: dict[str, str | None] = {}
    if payload.status is not None and payload.status != incident.status:
        incident.status = payload.status
        changed["status"] = payload.status
        if payload.status in ("resolved", "wontfix"):
            incident.resolved_by = admin.id
            incident.resolved_at = now
        else:
            # Re-opening — clear closure metadata.
            incident.resolved_by = None
            incident.resolved_at = None
    if payload.resolution_note is not None:
        incident.resolution_note = payload.resolution_note
        changed["resolution_note"] = payload.resolution_note
    await db.commit()
    await db.refresh(incident)

    await log_manager_activity(
        db,
        actor=admin.username,
        category="billing",
        status="success",
        detail_key="billing.incident.update",
        detail_params={"incident_id": incident_id, **changed},
    )
    return _serialize(incident)
