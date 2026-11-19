"""Admin routes for Pterodactyl Locations and Nodes lifecycle."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.contracts import OperationResult
from app.db.models.pterodactyl import PteroUser
from app.schemas.admin_nodes_locations import (
    AdminMessageResponse,
    LocationCreateIn,
    LocationListResponse,
    LocationOut,
    LocationUpdateIn,
    NodeConfigurationOut,
    NodeCreateIn,
    NodeListResponse,
    NodeOut,
)
from app.services import host_registry, node_management
from app.services.audit import log_manager_activity

router = APIRouter(prefix="/admin", tags=["admin-nodes-locations"])


def _request_origin(request: Request) -> str | None:
    origin = (request.headers.get("origin") or "").strip()
    if origin.lower().startswith(("http://", "https://")):
        return origin.rstrip("/")

    raw_proto = (
        (request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip().lower()
    )
    proto = raw_proto if raw_proto in ("http", "https") else request.url.scheme.lower()
    if proto not in ("http", "https"):
        return None

    forwarded_host = (
        (request.headers.get("x-forwarded-host") or "").split(",", 1)[0].strip()
    )
    host = (
        forwarded_host
        or (request.headers.get("host") or "").strip()
        or request.url.netloc
    )
    if not host:
        return None
    return f"{proto}://{host}".rstrip("/")


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------


@router.get("/locations", response_model=LocationListResponse)
async def list_locations(
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LocationListResponse:
    items = await node_management.list_locations(db)
    return LocationListResponse(locations=items)


@router.post(
    "/locations",
    response_model=LocationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_location(
    body: LocationCreateIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LocationOut:
    created = await node_management.create_location(db, body)

    await log_manager_activity(
        db,
        actor=admin.username,
        category="host_node",
        operation=OperationResult(
            action="location.create",
            phase="execution",
            outcome="success",
            target={"location_id": created.id, "short": created.short},
        ),
        detail_key="location.create",
        detail_params={"location_id": created.id, "short": created.short},
    )
    return created


@router.patch("/locations/{location_id}", response_model=LocationOut)
async def update_location(
    location_id: int,
    body: LocationUpdateIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LocationOut:
    updated = await node_management.update_location(db, location_id, body)

    await log_manager_activity(
        db,
        actor=admin.username,
        category="host_node",
        operation=OperationResult(
            action="location.update",
            phase="execution",
            outcome="success",
            target={"location_id": updated.id, "short": updated.short},
        ),
        detail_key="location.update",
        detail_params={"location_id": updated.id, "short": updated.short},
    )
    return updated


@router.delete("/locations/{location_id}", response_model=AdminMessageResponse)
async def delete_location(
    location_id: int,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminMessageResponse:
    deleted = await node_management.delete_location(db, location_id)

    await log_manager_activity(
        db,
        actor=admin.username,
        category="host_node",
        operation=OperationResult(
            action="location.delete",
            phase="execution",
            outcome="success",
            target={"location_id": deleted.id, "short": deleted.short},
        ),
        detail_key="location.delete",
        detail_params={"location_id": deleted.id, "short": deleted.short},
    )
    return AdminMessageResponse(message=f"地域 '{deleted.short}' 已删除")


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


@router.get("/nodes", response_model=NodeListResponse)
async def list_nodes(
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> NodeListResponse:
    items = await node_management.list_nodes(db)
    return NodeListResponse(nodes=items)


@router.post(
    "/nodes",
    response_model=NodeOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_node(
    body: NodeCreateIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> NodeOut:
    created = await node_management.create_node(db, body)

    await log_manager_activity(
        db,
        actor=admin.username,
        category="host_node",
        operation=OperationResult(
            action="node.create",
            phase="execution",
            outcome="success",
            target={"node_id": created.id, "name": created.name},
        ),
        detail_key="node.create",
        detail_params={
            "node_id": created.id,
            "name": created.name,
            "fqdn": created.fqdn,
            "location_id": created.location_id,
        },
    )
    return created


@router.get("/nodes/{node_id}/configuration", response_model=NodeConfigurationOut)
async def get_node_configuration(
    node_id: int,
    request: Request,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> NodeConfigurationOut:
    return await node_management.build_node_configuration(
        db, node_id, fallback_origin=_request_origin(request)
    )


@router.get(
    "/hosts/{host_id}/wings-configuration",
    response_model=NodeConfigurationOut,
)
async def get_host_wings_configuration(
    host_id: int,
    request: Request,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> NodeConfigurationOut:
    try:
        host = await host_registry.require_host_by_id(db, host_id)
    except host_registry.HostNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if host.kind != host_registry.KIND_WINGS_NODE or host.pterodactyl_node_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"主机 {host_id} 未绑定 Wings 节点",
        )
    return await node_management.build_node_configuration(
        db, host.pterodactyl_node_id, fallback_origin=_request_origin(request)
    )


@router.delete("/nodes/{node_id}", response_model=AdminMessageResponse)
async def delete_node(
    node_id: int,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminMessageResponse:
    deleted = await node_management.delete_node(db, node_id)

    await log_manager_activity(
        db,
        actor=admin.username,
        category="host_node",
        operation=OperationResult(
            action="node.delete",
            phase="execution",
            outcome="success",
            target={"node_id": deleted.id, "name": deleted.name},
        ),
        detail_key="node.delete",
        detail_params={"node_id": deleted.id, "name": deleted.name, "fqdn": deleted.fqdn},
    )
    return AdminMessageResponse(message=f"节点 '{deleted.name}' 已删除")
