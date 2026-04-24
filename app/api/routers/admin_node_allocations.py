"""Admin endpoints for managing port allocations on a Pterodactyl node.

Mirrors the Pterodactyl Panel "node allocations" UI: list all rows
(assigned + unassigned), create one or more allocations from a port
expression, delete unassigned allocations one-at-a-time or in bulk.

Allocations are pure ``panel.allocations`` rows — wings/agent are *not*
contacted; the rows become real ports only when a server uses them.

Design: ``docs/HOST_ALLOCATIONS_DESIGN.md``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.api.utils.port_expression import (
    PortExpressionError,
    parse_port_expression,
)
from app.db.models.pterodactyl import Allocation, PanelNode, PteroUser
from app.db.repositories.allocations import allocation_repository
from app.schemas.allocations import (
    AllocationBulkDeleteIn,
    AllocationCreateIn,
    AllocationCreateResponse,
    AllocationListResponse,
    AllocationOut,
    AllocationSkip,
    AllocationSummary,
    ServerBrief,
)
from app.services.audit import log_manager_activity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/nodes", tags=["admin-allocations"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ensure_node_exists(db: AsyncSession, node_id: int) -> PanelNode:
    node = await db.get(PanelNode, node_id)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"node {node_id} not found",
        )
    return node


def _serialize(row: Allocation, owner_name: str | None) -> AllocationOut:
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
    return AllocationOut(
        id=row.id,
        ip=row.ip,
        alias=row.ip_alias,
        port=row.port,
        notes=row.notes,
        server=server_brief,
    )


async def _serialize_many(
    db: AsyncSession, rows: list[Allocation]
) -> list[AllocationOut]:
    owner_ids = {r.server.owner_id for r in rows if r.server is not None}
    owners = await allocation_repository.get_owner_names(db, owner_ids)
    return [
        _serialize(r, owners.get(r.server.owner_id) if r.server else None)
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/{node_id}/allocations", response_model=AllocationListResponse,
)
async def list_node_allocations(
    node_id: int,
    assigned: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=191),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AllocationListResponse:
    await _ensure_node_exists(db, node_id)
    offset = (page - 1) * per_page
    items, total = await allocation_repository.list_all(
        db, node_id, assigned=assigned, search=search,
        limit=per_page, offset=offset,
    )
    serialized = await _serialize_many(db, items)
    assigned_count, unassigned_count = await allocation_repository.summary(db, node_id)
    return AllocationListResponse(
        items=serialized,
        page=page,
        per_page=per_page,
        total=total,
        summary=AllocationSummary(
            total=assigned_count + unassigned_count,
            assigned=assigned_count,
            unassigned=unassigned_count,
        ),
    )


@router.post(
    "/{node_id}/allocations",
    response_model=AllocationCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_node_allocations(
    node_id: int,
    body: AllocationCreateIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AllocationCreateResponse:
    await _ensure_node_exists(db, node_id)

    try:
        ports = parse_port_expression(body.ports)
    except PortExpressionError as exc:
        await log_manager_activity(
            db, actor=admin.username, action="allocation.create",
            status="error", detail_key="allocation.create.bad_expression",
            detail_params={"node_id": node_id, "ports": body.ports, "error": str(exc)},
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
        db, actor=admin.username, action="allocation.create", status="success",
        detail_key="allocation.create.ok",
        detail_params={
            "node_id": node_id, "ip": ip, "alias": alias,
            "ports": body.ports,
            "created_count": len(created),
            "skipped_count": len(skipped),
        },
    )

    return AllocationCreateResponse(
        created=serialized,
        skipped=[AllocationSkip(port=p, reason=r) for p, r in skipped],
    )


@router.delete(
    "/{node_id}/allocations/{allocation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_node_allocation(
    node_id: int,
    allocation_id: int,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _ensure_node_exists(db, node_id)

    snapshot, error = await allocation_repository.delete_one(
        db, node_id, allocation_id,
    )

    if error == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"allocation {allocation_id} not found on node {node_id}",
        )
    if error == "in_use":
        await log_manager_activity(
            db, actor=admin.username, action="allocation.delete",
            status="error", detail_key="allocation.delete.in_use",
            detail_params={
                "node_id": node_id, "allocation_id": allocation_id,
                "port": snapshot.port if snapshot else None,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"allocation {allocation_id} is in use",
        )

    await db.commit()
    assert snapshot is not None
    await log_manager_activity(
        db, actor=admin.username, action="allocation.delete", status="success",
        detail_key="allocation.delete.ok",
        detail_params={
            "node_id": node_id, "allocation_id": allocation_id,
            "ip": snapshot.ip, "port": snapshot.port,
        },
    )


@router.delete(
    "/{node_id}/allocations", status_code=status.HTTP_204_NO_CONTENT,
)
async def bulk_delete_node_allocations(
    node_id: int,
    body: AllocationBulkDeleteIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _ensure_node_exists(db, node_id)

    deleted, conflicting = await allocation_repository.delete_many(
        db, node_id, body.ids,
    )

    if not deleted:
        # delete_many returns ([], conflicting_or_missing) when blocked.
        conflict_ports = [r.port for r in conflicting]
        await log_manager_activity(
            db, actor=admin.username, action="allocation.delete_bulk",
            status="error", detail_key="allocation.delete.bulk_blocked",
            detail_params={
                "node_id": node_id, "ids": body.ids,
                "conflicting_ports": conflict_ports,
            },
        )
        if conflicting:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "some allocations are in use or do not belong to this node",
                    "conflicting_ports": conflict_ports,
                },
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="one or more allocations not found",
        )

    await db.commit()
    await log_manager_activity(
        db, actor=admin.username, action="allocation.delete_bulk",
        status="success", detail_key="allocation.delete.bulk_ok",
        detail_params={
            "node_id": node_id,
            "deleted_count": len(deleted),
            "ports": [r.port for r in deleted],
        },
    )
