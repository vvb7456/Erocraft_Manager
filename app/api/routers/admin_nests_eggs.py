"""Admin routes for Nest, Egg, EggVariable lifecycle and PTDL import/export."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.contracts import OperationResult
from app.db.models.pterodactyl import PteroUser
from app.schemas.admin_nests_eggs import (
    EggCreateIn,
    EggDetailOut,
    EggListResponse,
    EggMutationResponse,
    EggScriptsUpdateIn,
    EggUpdateIn,
    EggVariableCreateIn,
    EggVariableDeleteResponse,
    EggVariableMutationResponse,
    EggVariableUpdateIn,
    NestCreateIn,
    NestDetailOut,
    NestListResponse,
    NestOut,
    NestUpdateIn,
)
from app.schemas.admin_nodes_locations import AdminMessageResponse
from app.services import egg_management
from app.services.audit import log_manager_activity

router = APIRouter(prefix="/admin", tags=["admin-nests-eggs"])

_MAX_EGG_IMPORT_BYTES = 2 * 1024 * 1024  # 2 MiB


def _coerce_egg_json_obj(raw: Any, error_detail: str) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"egg_json 字符串解析失败: {exc}",
            ) from exc
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=error_detail,
        )
    return raw


async def _extract_import_payload(
    request: Request,
    *,
    require_nest_id: bool,
) -> tuple[int | None, dict[str, Any]]:
    """Support both JSON body and multipart/form-data file upload for Egg import."""
    content_type = (request.headers.get("content-type") or "").lower()

    if "multipart/form-data" in content_type:
        form = await request.form()
        nest_id_val: int | None = None
        if require_nest_id:
            raw_nest = form.get("nest_id")
            if raw_nest is None or not str(raw_nest).strip().isdigit():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="必须提供合法的 nest_id",
                )
            nest_id_val = int(str(raw_nest).strip())

        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="缺少上传文件字段 file",
            )
        raw_bytes = await upload.read(_MAX_EGG_IMPORT_BYTES + 1)
        if len(raw_bytes) > _MAX_EGG_IMPORT_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Egg JSON 文件大小不能超过 2MB",
            )
        try:
            parsed = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"上传文件不是合法的 UTF-8 JSON: {exc}",
            ) from exc
        if not isinstance(parsed, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Egg JSON 根节点必须是对象",
            )
        return nest_id_val, parsed

    raw_bytes = await request.body()
    if len(raw_bytes) > _MAX_EGG_IMPORT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Egg JSON 大小不能超过 2MB",
        )
    try:
        body = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"请求体不是合法的 JSON: {exc}",
        ) from exc
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="请求体必须是 JSON 对象",
        )

    if require_nest_id:
        raw_nest_id = body.get("nest_id")
        if not isinstance(raw_nest_id, int) or isinstance(raw_nest_id, bool) or raw_nest_id < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="必须提供合法的整型 nest_id",
            )
        return raw_nest_id, _coerce_egg_json_obj(
            body.get("egg_json"), "必须提供合法的 egg_json 对象"
        )

    # Overwrite import accepts either {"egg_json": {...}} or raw PTDL JSON directly
    raw_egg = body.get("egg_json") if "egg_json" in body else body
    return None, _coerce_egg_json_obj(raw_egg, "必须提供合法的 Egg JSON 对象")


# ---------------------------------------------------------------------------
# Nests
# ---------------------------------------------------------------------------


@router.get("/nests", response_model=NestListResponse)
async def list_nests(
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> NestListResponse:
    return NestListResponse(nests=await egg_management.list_nests(db))


@router.post("/nests", response_model=NestOut, status_code=status.HTTP_201_CREATED)
async def create_nest(
    body: NestCreateIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> NestOut:
    created = await egg_management.create_nest(db, body, author_email=admin.email)
    await log_manager_activity(
        db,
        actor=admin.username,
        category="server",
        operation=OperationResult(
            action="nest.create",
            phase="execution",
            outcome="success",
            target={"nest_id": created.id, "name": created.name},
        ),
        detail_key="nest.create",
        detail_params={"nest_id": created.id, "name": created.name},
    )
    return created


@router.get("/nests/{nest_id}", response_model=NestDetailOut)
async def get_nest(
    nest_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> NestDetailOut:
    return await egg_management.get_nest_detail(db, nest_id)


@router.patch("/nests/{nest_id}", response_model=NestOut)
async def update_nest(
    nest_id: int,
    body: NestUpdateIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> NestOut:
    updated = await egg_management.update_nest(db, nest_id, body)

    await log_manager_activity(
        db,
        actor=admin.username,
        category="server",
        operation=OperationResult(
            action="nest.update",
            phase="execution",
            outcome="success",
            target={"nest_id": updated.id, "name": updated.name},
        ),
        detail_key="nest.update",
        detail_params={"nest_id": updated.id, "name": updated.name},
    )
    return updated


@router.delete("/nests/{nest_id}", response_model=AdminMessageResponse)
async def delete_nest(
    nest_id: int,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminMessageResponse:
    deleted = await egg_management.delete_nest(db, nest_id)

    await log_manager_activity(
        db,
        actor=admin.username,
        category="server",
        operation=OperationResult(
            action="nest.delete",
            phase="execution",
            outcome="success",
            target={"nest_id": deleted.id, "name": deleted.name},
        ),
        detail_key="nest.delete",
        detail_params={"nest_id": deleted.id, "name": deleted.name},
    )
    return AdminMessageResponse(message=f"预设组 '{deleted.name}' 已删除")


# ---------------------------------------------------------------------------
# Eggs
# ---------------------------------------------------------------------------


@router.get("/eggs", response_model=EggListResponse)
async def list_eggs(
    nest_id: int | None = Query(default=None, ge=1),
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EggListResponse:
    return EggListResponse(eggs=await egg_management.list_eggs(db, nest_id=nest_id))


@router.post("/eggs", response_model=EggDetailOut, status_code=status.HTTP_201_CREATED)
async def create_egg(
    body: EggCreateIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EggDetailOut:
    created = await egg_management.create_egg(db, body, author_email=admin.email)

    await log_manager_activity(
        db,
        actor=admin.username,
        category="server",
        operation=OperationResult(
            action="egg.create",
            phase="execution",
            outcome="success",
            target={"egg_id": created.id, "nest_id": created.nest_id, "name": created.name},
        ),
        detail_key="egg.create",
        detail_params={"egg_id": created.id, "nest_id": created.nest_id, "name": created.name},
    )
    return created


@router.post(
    "/eggs/import",
    response_model=EggDetailOut,
    status_code=status.HTTP_201_CREATED,
)
async def import_egg(
    request: Request,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EggDetailOut:
    nest_id, raw_json = await _extract_import_payload(request, require_nest_id=True)
    assert nest_id is not None
    created = await egg_management.import_egg_new(
        db,
        nest_id=nest_id,
        raw_json=raw_json,
        fallback_author=admin.email,
    )

    await log_manager_activity(
        db,
        actor=admin.username,
        category="server",
        operation=OperationResult(
            action="egg.import",
            phase="execution",
            outcome="success",
            target={"egg_id": created.id, "nest_id": created.nest_id, "name": created.name},
        ),
        detail_key="egg.import",
        detail_params={
            "egg_id": created.id,
            "nest_id": created.nest_id,
            "name": created.name,
            "variables_count": len(created.variables),
        },
    )
    return created


@router.get("/eggs/{egg_id}", response_model=EggDetailOut)
async def get_egg(
    egg_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EggDetailOut:
    return await egg_management.get_egg_detail(db, egg_id)


@router.patch("/eggs/{egg_id}", response_model=EggMutationResponse)
async def update_egg(
    egg_id: int,
    body: EggUpdateIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EggMutationResponse:
    detail, affected = await egg_management.update_egg(db, egg_id, body)

    await log_manager_activity(
        db,
        actor=admin.username,
        category="server",
        operation=OperationResult(
            action="egg.update",
            phase="execution",
            outcome="success",
            target={"egg_id": detail.id, "name": detail.name},
        ),
        detail_key="egg.update",
        detail_params={"egg_id": detail.id, "name": detail.name},
    )
    return EggMutationResponse(egg=detail, affected_plans=affected)


@router.patch("/eggs/{egg_id}/scripts", response_model=EggDetailOut)
async def update_egg_scripts(
    egg_id: int,
    body: EggScriptsUpdateIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EggDetailOut:
    detail = await egg_management.update_egg_scripts(db, egg_id, body)

    await log_manager_activity(
        db,
        actor=admin.username,
        category="server",
        operation=OperationResult(
            action="egg.scripts.update",
            phase="execution",
            outcome="success",
            target={"egg_id": detail.id, "name": detail.name},
        ),
        detail_key="egg.scripts.update",
        detail_params={"egg_id": detail.id, "name": detail.name},
    )
    return detail


@router.put("/eggs/{egg_id}/import", response_model=EggMutationResponse)
async def overwrite_import_egg(
    egg_id: int,
    request: Request,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EggMutationResponse:
    _, raw_json = await _extract_import_payload(request, require_nest_id=False)
    detail, affected = await egg_management.import_egg_overwrite(
        db, egg_id=egg_id, raw_json=raw_json
    )

    await log_manager_activity(
        db,
        actor=admin.username,
        category="server",
        operation=OperationResult(
            action="egg.import_overwrite",
            phase="execution",
            outcome="success",
            target={"egg_id": detail.id, "name": detail.name},
        ),
        detail_key="egg.import_overwrite",
        detail_params={
            "egg_id": detail.id,
            "name": detail.name,
            "variables_count": len(detail.variables),
        },
    )
    return EggMutationResponse(egg=detail, affected_plans=affected)


@router.get("/eggs/{egg_id}/export")
async def export_egg(
    egg_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    filename, payload = await egg_management.export_egg_json(db, egg_id)

    return Response(
        content=payload.encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.delete("/eggs/{egg_id}", response_model=AdminMessageResponse)
async def delete_egg(
    egg_id: int,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminMessageResponse:
    deleted = await egg_management.delete_egg(db, egg_id)

    await log_manager_activity(
        db,
        actor=admin.username,
        category="server",
        operation=OperationResult(
            action="egg.delete",
            phase="execution",
            outcome="success",
            target={"egg_id": deleted.id, "name": deleted.name},
        ),
        detail_key="egg.delete",
        detail_params={"egg_id": deleted.id, "name": deleted.name},
    )
    return AdminMessageResponse(message=f"Egg '{deleted.name}' 已删除")


# ---------------------------------------------------------------------------
# Egg Variables
# ---------------------------------------------------------------------------


@router.post(
    "/eggs/{egg_id}/variables",
    response_model=EggVariableMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_egg_variable(
    egg_id: int,
    body: EggVariableCreateIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EggVariableMutationResponse:
    var_out, affected = await egg_management.create_egg_variable(db, egg_id, body)

    await log_manager_activity(
        db,
        actor=admin.username,
        category="server",
        operation=OperationResult(
            action="egg.variable.create",
            phase="execution",
            outcome="success",
            target={"egg_id": egg_id, "variable_id": var_out.id, "env_variable": var_out.env_variable},
        ),
        detail_key="egg.variable.create",
        detail_params={
            "egg_id": egg_id,
            "variable_id": var_out.id,
            "env_variable": var_out.env_variable,
        },
    )
    return EggVariableMutationResponse(variable=var_out, affected_plans=affected)


@router.patch(
    "/eggs/{egg_id}/variables/{var_id}",
    response_model=EggVariableMutationResponse,
)
async def update_egg_variable(
    egg_id: int,
    var_id: int,
    body: EggVariableUpdateIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EggVariableMutationResponse:
    var_out, affected = await egg_management.update_egg_variable(
        db, egg_id, var_id, body
    )

    await log_manager_activity(
        db,
        actor=admin.username,
        category="server",
        operation=OperationResult(
            action="egg.variable.update",
            phase="execution",
            outcome="success",
            target={"egg_id": egg_id, "variable_id": var_out.id, "env_variable": var_out.env_variable},
        ),
        detail_key="egg.variable.update",
        detail_params={
            "egg_id": egg_id,
            "variable_id": var_out.id,
            "env_variable": var_out.env_variable,
        },
    )
    return EggVariableMutationResponse(variable=var_out, affected_plans=affected)


@router.delete(
    "/eggs/{egg_id}/variables/{var_id}",
    response_model=EggVariableDeleteResponse,
)
async def delete_egg_variable(
    egg_id: int,
    var_id: int,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EggVariableDeleteResponse:
    deleted, affected = await egg_management.delete_egg_variable(db, egg_id, var_id)

    await log_manager_activity(
        db,
        actor=admin.username,
        category="server",
        operation=OperationResult(
            action="egg.variable.delete",
            phase="execution",
            outcome="success",
            target={"egg_id": egg_id, "variable_id": deleted.id, "env_variable": deleted.env_variable},
        ),
        detail_key="egg.variable.delete",
        detail_params={
            "egg_id": egg_id,
            "variable_id": deleted.id,
            "env_variable": deleted.env_variable,
        },
    )
    return EggVariableDeleteResponse(
        message=f"环境变量 '{deleted.env_variable}' 已删除",
        affected_plans=affected,
    )
