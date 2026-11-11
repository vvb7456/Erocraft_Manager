"""Admin routes for redemption code batches, exports, and codes."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.db.models.pterodactyl import PteroUser
from app.schemas.redemption import (
    RedemptionBatchCreateRequest,
    RedemptionBatchDetailOut,
    RedemptionBatchListResponse,
    RedemptionBatchOut,
    RedemptionBatchVoidOut,
    RedemptionCodeListResponse,
    RedemptionCodeOut,
    RedemptionExportCreateRequest,
    RedemptionVoidRequest,
)
from app.services.billing import redemption as svc

router = APIRouter(prefix="/admin/billing/redemption", tags=["billing"])


def _txt_download_response(filename: str, content: str) -> Response:
    encoded = quote(filename)
    return Response(
        content=content.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"redemption-codes.txt\"; filename*=UTF-8''{encoded}",
            "Cache-Control": "no-store",
        },
    )


@router.get("/batches", response_model=RedemptionBatchListResponse)
async def list_batches(
    source: str | None = Query(default=None),
    plan_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedemptionBatchListResponse:
    return await svc.list_batches(
        db, source=source, plan_id=plan_id, q=q, limit=limit, offset=offset
    )


@router.post(
    "/batches",
    response_model=RedemptionBatchOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_batch(
    payload: RedemptionBatchCreateRequest,
    actor: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedemptionBatchOut:
    return await svc.create_batch(db, payload=payload, actor=actor)


@router.get("/batches/{batch_id}", response_model=RedemptionBatchDetailOut)
async def get_batch_detail(
    batch_id: int,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedemptionBatchDetailOut:
    return await svc.get_batch_detail(db, batch_id)


@router.post("/batches/{batch_id}/export")
async def export_batch_codes(
    batch_id: int,
    payload: RedemptionExportCreateRequest,
    actor: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    export_row, txt = await svc.create_export(
        db, batch_id=batch_id, quantity=payload.quantity, actor=actor
    )
    filename = f"redemption_batch_{batch_id}_export_{export_row.id}.txt"
    return _txt_download_response(filename, txt)


@router.get("/exports/{export_id}/download")
async def download_export(
    export_id: int,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    export_row, txt = await svc.get_export_txt(db, export_id=export_id)
    filename = f"redemption_batch_{export_row.batch_id}_export_{export_row.id}.txt"
    return _txt_download_response(filename, txt)


@router.post("/batches/{batch_id}/void", response_model=RedemptionBatchVoidOut)
async def void_batch(
    batch_id: int,
    payload: RedemptionVoidRequest,
    actor: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedemptionBatchVoidOut:
    return await svc.void_batch(
        db, batch_id=batch_id, reason=payload.reason, actor=actor
    )


@router.get("/codes", response_model=RedemptionCodeListResponse)
async def list_codes(
    batch_id: int | None = Query(default=None),
    status_: str | None = Query(default=None, alias="status"),
    export_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedemptionCodeListResponse:
    return await svc.list_codes(
        db,
        batch_id=batch_id,
        status_filter=status_,
        export_id=export_id,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.post("/codes/{code_id}/void", response_model=RedemptionCodeOut)
async def void_code(
    code_id: int,
    payload: RedemptionVoidRequest,
    actor: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedemptionCodeOut:
    return await svc.void_code(
        db, code_id=code_id, reason=payload.reason, actor=actor
    )
