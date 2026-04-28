"""Admin server detail routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.api.utils.wings_errors import translate_wings_error
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
from app.services import server_lifecycle, server_management
from app.services.audit import log_manager_activity
from app.services.server_lifecycle import LifecycleError
from app.services.server_management import (
    ServerManagementError,
    ServerManagementValidationError,
    ServerNotFoundError,
)
from app.services.wings import WingsServiceError

router = APIRouter(prefix="/admin/servers", tags=["admin-server-detail"])


def _server_management_http(exc: ServerManagementError) -> HTTPException:
    if isinstance(exc, ServerNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ServerManagementValidationError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.get("/{server_id}", response_model=AdminServerDetailResponse)
async def get_admin_server_detail(
    server_id: int,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminServerDetailResponse:
    try:
        return await server_management.get_server_detail(db, server_id)
    except ServerManagementError as exc:
        raise _server_management_http(exc) from exc


@router.get("/{server_id}/runtime", response_model=ServerRuntimeResponse)
async def get_admin_server_runtime(
    server_id: int,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ServerRuntimeResponse:
    try:
        return await server_management.get_runtime(db, server_id)
    except ServerManagementValidationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
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
    try:
        await server_management.update_details(
            db,
            server_id,
            name=payload.name,
            description=payload.description,
            external_id=payload.external_id,
            provided=payload.model_fields_set,
        )
    except ServerManagementError as exc:
        raise _server_management_http(exc) from exc
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        status="success",
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
    try:
        warning = await server_management.update_owner(
            db,
            server_id,
            owner_id=payload.owner_id,
        )
    except ServerManagementError as exc:
        raise _server_management_http(exc) from exc
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        status="warning" if warning else "success",
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
    try:
        await server_management.update_build(
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
    except ServerManagementError as exc:
        raise _server_management_http(exc) from exc
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        status="success",
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
    try:
        allocations = await server_management.list_available_allocations(db, server_id)
    except ServerManagementError as exc:
        raise _server_management_http(exc) from exc
    return AvailableAllocationsResponse(allocations=allocations)


@router.post("/{server_id}/allocations", response_model=MessageResponse)
async def add_admin_server_allocations(
    server_id: int,
    payload: AllocationIdsRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    try:
        await server_management.add_allocations(
            db,
            server_id,
            allocation_ids=payload.allocation_ids,
        )
    except ServerManagementError as exc:
        raise _server_management_http(exc) from exc
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        status="success",
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
    try:
        await server_management.remove_allocation(db, server_id, allocation_id)
    except ServerManagementError as exc:
        raise _server_management_http(exc) from exc
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        status="success",
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
    try:
        await server_management.set_primary_allocation(
            db,
            server_id,
            payload.allocation_id,
        )
    except ServerManagementError as exc:
        raise _server_management_http(exc) from exc
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        status="success",
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
    try:
        await server_management.update_startup(
            db,
            server_id,
            image=payload.image,
            startup=payload.startup,
            skip_scripts=payload.skip_scripts,
            provided=payload.model_fields_set,
        )
    except ServerManagementError as exc:
        raise _server_management_http(exc) from exc
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        status="success",
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
    try:
        await server_management.switch_egg(
            db,
            server_id,
            nest_id=payload.nest_id,
            egg_id=payload.egg_id,
            environment=payload.environment,
            image=payload.image,
            startup=payload.startup,
            skip_scripts=payload.skip_scripts,
            provided=payload.model_fields_set,
        )
    except ServerManagementError as exc:
        raise _server_management_http(exc) from exc
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        status="success",
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
    try:
        await server_management.update_variables(db, server_id, variables=payload.variables)
    except ServerManagementError as exc:
        raise _server_management_http(exc) from exc
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        status="success",
        detail_key="admin_server.variables.update",
        detail_params={"server_id": server_id, "variables": sorted(payload.variables)},
    )
    return MessageResponse(message="服务器变量已更新")


@router.post("/{server_id}/reinstall", response_model=MessageResponse)
async def reinstall_admin_server(
    server_id: int,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    try:
        await server_lifecycle.reinstall_server(db, server_id)
    except LifecycleError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="server",
        status="success",
        detail_key="admin_server.reinstall",
        detail_params={"server_id": server_id},
    )
    return MessageResponse(message="服务器已开始重装")
