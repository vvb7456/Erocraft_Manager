"""Admin server detail routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.api.utils.wings_errors import translate_wings_error
from app.core.contracts import ErrorInfo, OperationResult
from app.db.models import PteroUser
from app.schemas.admin_server_detail import (
    AdminServerDetailResponse,
    AllocationIdsRequest,
    AvailableAllocationsResponse,
    MutationWarningResponse,
    PrimaryAllocationRequest,
    ServerRuntimeResponse,
    SwitchEggRequest,
    UpdateServerBuildRequest,
    UpdateServerDetailsRequest,
    UpdateServerOwnerRequest,
    UpdateStartupRequest,
    UpdateVariablesRequest,
)
from app.schemas.servers import MessageResponse
from app.services.audit import log_manager_activity
from app.services.server_engine import (
    get_server_detail,
    get_server_runtime,
    list_available_allocations,
    server_engine,
)
from app.services.wings import WingsServiceError

router = APIRouter(prefix="/admin/servers", tags=["admin-server-detail"])


@router.get("/{server_id}", response_model=AdminServerDetailResponse)
async def get_admin_server_detail(
    server_id: int,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminServerDetailResponse:
    return await get_server_detail(db, server_id)


@router.get("/{server_id}/runtime", response_model=ServerRuntimeResponse)
async def get_admin_server_runtime(
    server_id: int,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ServerRuntimeResponse:
    try:
        return await get_server_runtime(db, server_id)
    except WingsServiceError as exc:
        raise translate_wings_error(exc) from exc


@router.patch("/{server_id}/details", response_model=MessageResponse)
async def update_admin_server_details(
    server_id: int,
    payload: UpdateServerDetailsRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    if not payload.model_fields_set:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无有效更新内容")
    await server_engine.update_details(
        db,
        server_id,
        name=payload.name,
        description=payload.description,
        external_id=payload.external_id,
        provided=payload.model_fields_set,
    )
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        operation=OperationResult(action="server.details.update", phase="execution", outcome="success", target={"server_id": server_id}),
        detail_key="admin_server.details.update",
        detail_params={"server_id": server_id},
    )
    return MessageResponse(message="服务器基础信息已更新")


@router.patch("/{server_id}/owner", response_model=MutationWarningResponse)
async def update_admin_server_owner(
    server_id: int,
    payload: UpdateServerOwnerRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MutationWarningResponse:
    result = await server_engine.update_owner(
        db,
        server_id,
        owner_id=payload.owner_id,
    )
    warning = result.warnings[0] if result.warnings else None
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        operation=OperationResult(
            action="server.owner.update", phase="execution", outcome="success", target={"server_id": server_id, "owner_id": payload.owner_id},
            children=[OperationResult(action="wings.owner.deauthorize", phase="execution", outcome="failed", target={"server_id": server_id}, error=ErrorInfo(code="dependency.failed", detail=warning))] if warning else [],
        ),
        detail_key="admin_server.owner.update",
        detail_params={"server_id": server_id, "owner_id": payload.owner_id},
    )
    return MutationWarningResponse(message="服务器所有者已更新", warning=warning)


@router.patch("/{server_id}/build", response_model=MessageResponse)
async def update_admin_server_build(
    server_id: int,
    payload: UpdateServerBuildRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    if not payload.model_fields_set:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无有效更新内容")
    await server_engine.update_build(
        db,
        server_id,
        memory=payload.memory,
        swap=payload.swap,
        disk=payload.disk,
        io=payload.io,
        cpu=payload.cpu,
        threads=payload.threads,
        update_threads="threads" in payload.model_fields_set,
        oom_disabled=payload.oom_disabled,
        allocation_limit=payload.allocation_limit,
        database_limit=payload.database_limit,
        backup_limit=payload.backup_limit,
    )
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        operation=OperationResult(action="server.build.update", phase="execution", outcome="success", target={"server_id": server_id}),
        detail_key="admin_server.build.update",
        detail_params={"server_id": server_id},
    )
    return MessageResponse(message="服务器资源配置已更新")


@router.get("/{server_id}/allocations/available", response_model=AvailableAllocationsResponse)
async def list_admin_server_available_allocations(
    server_id: int,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AvailableAllocationsResponse:
    allocations = await list_available_allocations(db, server_id)
    return AvailableAllocationsResponse(allocations=allocations)


@router.post("/{server_id}/allocations", response_model=MessageResponse)
async def add_admin_server_allocations(
    server_id: int,
    payload: AllocationIdsRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await server_engine.add_allocations(
        db,
        server_id,
        allocation_ids=payload.allocation_ids,
    )
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        operation=OperationResult(action="server.allocations.add", phase="execution", outcome="success", target={"server_id": server_id, "allocation_ids": payload.allocation_ids}),
        detail_key="admin_server.allocations.add",
        detail_params={"server_id": server_id, "allocation_ids": payload.allocation_ids},
    )
    return MessageResponse(message="服务器分配已添加")


@router.delete("/{server_id}/allocations/{allocation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_admin_server_allocation(
    server_id: int,
    allocation_id: int,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await server_engine.remove_allocation(db, server_id, allocation_id)
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        operation=OperationResult(action="server.allocations.remove", phase="execution", outcome="success", target={"server_id": server_id, "allocation_id": allocation_id}),
        detail_key="admin_server.allocations.remove",
        detail_params={"server_id": server_id, "allocation_id": allocation_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{server_id}/allocations/primary", response_model=MessageResponse)
async def set_admin_server_primary_allocation(
    server_id: int,
    payload: PrimaryAllocationRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await server_engine.set_primary_allocation(
        db,
        server_id,
        payload.allocation_id,
    )
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        operation=OperationResult(action="server.allocations.primary", phase="execution", outcome="success", target={"server_id": server_id, "allocation_id": payload.allocation_id}),
        detail_key="admin_server.allocations.primary",
        detail_params={"server_id": server_id, "allocation_id": payload.allocation_id},
    )
    return MessageResponse(message="服务器主分配已更新")


@router.patch("/{server_id}/startup", response_model=MessageResponse)
async def update_admin_server_startup(
    server_id: int,
    payload: UpdateStartupRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    if not payload.model_fields_set:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无有效更新内容")
    await server_engine.update_startup(
        db,
        server_id,
        image=payload.image,
        startup=payload.startup,
        skip_scripts=payload.skip_scripts,
        provided=payload.model_fields_set,
    )
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        operation=OperationResult(action="server.startup.update", phase="execution", outcome="success", target={"server_id": server_id}),
        detail_key="admin_server.startup.update",
        detail_params={"server_id": server_id},
    )
    return MessageResponse(message="服务器启动配置已更新")


@router.put("/{server_id}/egg", response_model=MessageResponse)
async def switch_admin_server_egg(
    server_id: int,
    payload: SwitchEggRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await server_engine.switch_egg(
        db,
        server_id,
        egg_id=payload.egg_id,
        environment=payload.environment,
        image=payload.image,
        startup=payload.startup,
        skip_scripts=payload.skip_scripts,
        provided=payload.model_fields_set,
    )
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        operation=OperationResult(action="server.egg.switch", phase="execution", outcome="success", target={"server_id": server_id, "egg_id": payload.egg_id}),
        detail_key="admin_server.egg.switch",
        detail_params={"server_id": server_id, "egg_id": payload.egg_id},
    )
    return MessageResponse(message="服务器 Egg 已更新")


@router.patch("/{server_id}/variables", response_model=MessageResponse)
async def update_admin_server_variables(
    server_id: int,
    payload: UpdateVariablesRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await server_engine.update_variables(db, server_id, variables=payload.variables)
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        operation=OperationResult(action="server.variables.update", phase="execution", outcome="success", target={"server_id": server_id}),
        detail_key="admin_server.variables.update",
        detail_params={"server_id": server_id, "variables": sorted(payload.variables)},
    )
    return MessageResponse(message="服务器变量已更新")


class AdminReinstallRequest(BaseModel):
    force: bool = False


@router.post("/{server_id}/reinstall", response_model=MessageResponse)
async def reinstall_admin_server(
    server_id: int,
    payload: AdminReinstallRequest | None = Body(default=None),
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    force = bool(payload.force) if payload is not None else False
    await server_engine.reinstall_server(
        db,
        server_id,
        force=force,
        forbid_suspended=False,
    )
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        operation=OperationResult(action="server.reinstall", phase="acceptance", outcome="success", target={"server_id": server_id}),
        detail_key="admin_server.reinstall",
        detail_params={"server_id": server_id},
    )
    return MessageResponse(message="服务器已开始重装")
