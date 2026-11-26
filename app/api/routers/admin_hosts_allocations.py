"""Admin endpoints for managing port allocations on a wings node, keyed by host id.

Mirrors the Pterodactyl Panel "node allocations" UI: list all rows
(assigned + unassigned), create one or more allocations from a port
expression, delete unassigned allocations one-at-a-time or in bulk.

Allocations are pure ``panel.allocations`` rows — wings/agent are *not*
contacted; the rows become real ports only when a server uses them.

Routes are keyed by ``manager_hosts.id`` (the canonical inventory id)
and resolve to the bound ``panel.nodes`` row internally via
``host.pterodactyl_node_id``. Non-wings hosts return 400.

Design: ``docs/HOST_ALLOCATIONS_DESIGN.md``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.api.utils.port_expression import (
    PortExpressionError,
    parse_port_expression,
)
from app.core.time import to_iso_z, utc_naive_now_sec
from app.db.models.pterodactyl import Allocation, PanelNode, PteroUser
from app.db.repositories.allocation_reservations import is_allocation_actively_reserved
from app.db.repositories.allocations import allocation_repository
from app.schemas.allocations import (
    AllocationBulkDeleteIn,
    AllocationCreateIn,
    AllocationCreateResponse,
    AllocationListResponse,
    AllocationOut,
    AllocationSkip,
    AllocationSummary,
    AllocationUpdateIn,
    ServerBrief,
)
from app.services import host_registry
from app.services.audit import log_manager_activity
from app.core.contracts import OperationResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/hosts", tags=["admin-allocations"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_node_id(db: AsyncSession, host_id: int) -> int:
    """Return the panel ``nodes.id`` for a wings_node host.

    404 when the host doesn't exist; 400 when the host is not a wings_node
    or has no panel binding (allocations only apply to wings nodes).
    """
    try:
        host = await host_registry.require_host_by_id(db, host_id)
    except host_registry.HostNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc),
        ) from exc
    if host.kind != host_registry.KIND_WINGS_NODE or host.pterodactyl_node_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"host {host_id} is not a wings_node with a panel binding "
                "(allocations only apply to wings nodes)"
            ),
        )
    if await db.get(PanelNode, host.pterodactyl_node_id) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"host {host_id} references panel node "
                f"{host.pterodactyl_node_id}, which no longer exists"
            ),
        )
    return host.pterodactyl_node_id


def _serialize(
    row: Allocation,
    owner_name: str | None,
    *,
    reserved_order_no: str | None = None,
    now: datetime | None = None,
) -> AllocationOut:
    server = row.server
    server_brief: ServerBrief | None = None
    if server is not None:
        server_brief = ServerBrief(
            id=server.id,
            uuid_short=server.uuid_short,
            name=server.name,
            owner_id=server.owner_id,
            owner_name=owner_name,
        )
    actively_reserved = is_allocation_actively_reserved(row, now)
    return AllocationOut(
        id=row.id,
        ip=row.ip,
        alias=row.ip_alias,
        port=row.port,
        notes=row.notes,
        server=server_brief,
        reserved_order_id=row.reserved_order_id if actively_reserved else None,
        reserved_order_no=reserved_order_no if actively_reserved else None,
        reserved_until=(
            to_iso_z(row.reserved_until)
            if actively_reserved and row.reserved_until is not None
            else None
        ),
    )


async def _serialize_many(
    db: AsyncSession,
    rows: list[Allocation],
    *,
    order_nos_by_id: dict[int, str | None] | None = None,
    now: datetime | None = None,
) -> list[AllocationOut]:
    ts = now if now is not None else utc_naive_now_sec()
    owner_ids = {r.server.owner_id for r in rows if r.server is not None}
    owners = await allocation_repository.get_owner_names(db, owner_ids)
    order_nos: dict[int, str | None]
    if order_nos_by_id is not None:
        order_nos = order_nos_by_id
    else:
        reserved_ids = {
            int(r.reserved_order_id)
            for r in rows
            if is_allocation_actively_reserved(r, ts) and r.reserved_order_id is not None
        }
        fetched = await allocation_repository.get_order_nos(db, reserved_ids)
        order_nos = {oid: ono for oid, ono in fetched.items()}
    return [
        _serialize(
            r,
            owners.get(r.server.owner_id) if r.server else None,
            reserved_order_no=(
                order_nos.get(int(r.reserved_order_id))
                if r.reserved_order_id is not None
                else None
            ),
            now=ts,
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/{host_id}/allocations", response_model=AllocationListResponse,
)
async def list_host_allocations(
    host_id: int,
    assigned: bool | None = Query(default=None),
    reserved: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=191),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    sort_by: Literal["ip", "alias", "port", "server"] | None = Query(default=None),
    sort_order: Literal["asc", "desc"] = Query(default="asc"),
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AllocationListResponse:
    node_id = await _resolve_node_id(db, host_id)
    offset = (page - 1) * per_page
    ts = utc_naive_now_sec()
    pairs, total = await allocation_repository.list_all(
        db, node_id, assigned=assigned, reserved=reserved, search=search,
        limit=per_page, offset=offset,
        sort_by=sort_by, sort_order=sort_order,
        now=ts,
    )
    items = [alloc for alloc, _ in pairs]
    order_nos_by_id = {
        int(alloc.reserved_order_id): order_no
        for alloc, order_no in pairs
        if alloc.reserved_order_id is not None
    }
    serialized = await _serialize_many(
        db, items, order_nos_by_id=order_nos_by_id, now=ts
    )
    assigned_count, reserved_count, free_count = await allocation_repository.summary(
        db, node_id, now=ts
    )
    return AllocationListResponse(
        items=serialized,
        page=page,
        per_page=per_page,
        total=total,
        summary=AllocationSummary(
            total=assigned_count + reserved_count + free_count,
            assigned=assigned_count,
            reserved=reserved_count,
            unassigned=free_count,
        ),
    )


@router.post(
    "/{host_id}/allocations",
    response_model=AllocationCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_host_allocations(
    host_id: int,
    body: AllocationCreateIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AllocationCreateResponse:
    node_id = await _resolve_node_id(db, host_id)

    try:
        ports = parse_port_expression(body.ports)
    except PortExpressionError as exc:
        await log_manager_activity(
            db, actor=admin.username, category="server",
            operation=OperationResult(action="allocation.create", phase="request", outcome="failed", target={"host_id": host_id, "node_id": node_id}), detail_key="allocation.create.bad_expression",
            detail_params={
                "host_id": host_id, "node_id": node_id,
                "ports": body.ports, "error": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        ) from exc

    ip = body.ip.strip()
    alias = body.alias.strip() if body.alias else None
    if alias == "":
        alias = None

    try:
        created, skipped = await allocation_repository.bulk_create(
            db, node_id, ip, alias, ports,
        )
    except Exception as exc:  # IntegrityError on race
        logger.exception("allocation bulk_create failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="failed to create allocations (concurrent write?)",
        ) from exc

    await db.commit()

    serialized = await _serialize_many(db, created)

    await log_manager_activity(
        db, actor=admin.username, category="server",
        operation=OperationResult(action="allocation.create", phase="execution", outcome="success", target={"host_id": host_id, "node_id": node_id}, succeeded=len(created), facts={"skipped": len(skipped)}),
        detail_key="allocation.create.ok",
        detail_params={
            "host_id": host_id, "node_id": node_id,
            "ip": ip, "alias": alias,
            "ports": body.ports,
            "created_count": len(created),
            "skipped_count": len(skipped),
        },
    )

    return AllocationCreateResponse(
        created=serialized,
        skipped=[AllocationSkip(port=p, reason=r) for p, r in skipped],
    )


@router.patch(
    "/{host_id}/allocations/{allocation_id}",
    response_model=AllocationOut,
)
async def update_host_allocation(
    host_id: int,
    allocation_id: int,
    body: AllocationUpdateIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AllocationOut:
    node_id = await _resolve_node_id(db, host_id)
    row = await allocation_repository.get(db, node_id, allocation_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"allocation {allocation_id} not found on host {host_id}",
        )

    changed: dict[str, str | None] = {}
    if "alias" in body.model_fields_set and row.ip_alias != body.alias:
        row.ip_alias = body.alias
        changed["alias"] = body.alias
    if "notes" in body.model_fields_set and row.notes != body.notes:
        row.notes = body.notes
        changed["notes"] = body.notes

    if changed:
        row.updated_at = utc_naive_now_sec()
        await db.commit()
        await db.refresh(row)

    serialized = (await _serialize_many(db, [row]))[0]

    if changed:
        await log_manager_activity(
            db,
            actor=admin.username,
            category="server",
            operation=OperationResult(
                action="allocation.update",
                phase="execution",
                outcome="success",
                target={"host_id": host_id, "node_id": node_id, "allocation_id": allocation_id},
            ),
            detail_key="allocation.update.ok",
            detail_params={
                "host_id": host_id,
                "node_id": node_id,
                "allocation_id": allocation_id,
                "ip": row.ip,
                "port": row.port,
                "alias": row.ip_alias,
                "notes": row.notes,
                "changed_fields": sorted(changed.keys()),
            },
        )
    return serialized


@router.delete(
    "/{host_id}/allocations/{allocation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_host_allocation(
    host_id: int,
    allocation_id: int,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    node_id = await _resolve_node_id(db, host_id)

    snapshot, error = await allocation_repository.delete_one(
        db, node_id, allocation_id,
    )

    if error == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"allocation {allocation_id} not found on host {host_id}",
        )
    if error in ("in_use", "reserved"):
        actor_name = str(admin.username)
        port_val = int(snapshot.port) if snapshot is not None else None
        await db.rollback()
        await log_manager_activity(
            db, actor=actor_name, category="server",
            operation=OperationResult(action="allocation.delete", phase="request", outcome="failed", target={"host_id": host_id, "allocation_id": allocation_id}), detail_key="allocation.delete.in_use",
            detail_params={
                "host_id": host_id, "node_id": node_id,
                "allocation_id": allocation_id,
                "port": port_val,
            },
        )
        detail_msg = (
            f"allocation {allocation_id} is reserved by an active order"
            if error == "reserved"
            else f"allocation {allocation_id} is in use"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail_msg,
        )

    await db.commit()
    assert snapshot is not None
    await log_manager_activity(
        db, actor=admin.username, category="server",
        operation=OperationResult(action="allocation.delete", phase="execution", outcome="success", target={"host_id": host_id, "allocation_id": allocation_id}),
        detail_key="allocation.delete.ok",
        detail_params={
            "host_id": host_id, "node_id": node_id,
            "allocation_id": allocation_id,
            "ip": snapshot.ip, "port": snapshot.port,
        },
    )


@router.delete(
    "/{host_id}/allocations", status_code=status.HTTP_204_NO_CONTENT,
)
async def bulk_delete_host_allocations(
    host_id: int,
    body: AllocationBulkDeleteIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    node_id = await _resolve_node_id(db, host_id)

    deleted, conflicting = await allocation_repository.delete_many(
        db, node_id, body.ids,
    )

    if not deleted:
        actor_name = str(admin.username)
        conflict_ports = [int(r.port) for r in conflicting]
        await db.rollback()
        await log_manager_activity(
            db, actor=actor_name, category="server",
            operation=OperationResult(action="allocation.batch_delete", phase="request", outcome="failed", target={"host_id": host_id, "allocation_ids": body.ids}), detail_key="allocation.delete.bulk_blocked",
            detail_params={
                "host_id": host_id, "node_id": node_id,
                "ids": body.ids,
                "conflicting_ports": conflict_ports,
            },
        )
        if conflicting:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "some allocations are in use or do not belong to this host",
                    "conflicting_ports": conflict_ports,
                },
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="one or more allocations not found",
        )

    await db.commit()
    await log_manager_activity(
        db, actor=admin.username, category="server",
        operation=OperationResult(action="allocation.batch_delete", phase="execution", outcome="success", target={"host_id": host_id, "node_id": node_id}, succeeded=len(deleted), failed=0), detail_key="allocation.delete.bulk_ok",
        detail_params={
            "host_id": host_id, "node_id": node_id,
            "deleted_count": len(deleted),
            "ports": [r.port for r in deleted],
        },
    )
