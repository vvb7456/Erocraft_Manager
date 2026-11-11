"""User-facing redemption code preview and execution endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.core.rate_limit import limiter
from app.db.models.pterodactyl import PteroUser
from app.schemas.redemption import (
    RedeemExecuteRequest,
    RedeemExecuteResponse,
    RedeemPreviewRequest,
    RedeemPreviewResponse,
)
from app.services.billing import redemption as svc

router = APIRouter(prefix="/user/redemptions", tags=["billing"])


@router.post("/preview", response_model=RedeemPreviewResponse)
@limiter.limit("30/minute")
async def preview_redemption_code(
    payload: RedeemPreviewRequest,
    request: Request,
    user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RedeemPreviewResponse:
    return await svc.preview_code(db, user=user, raw_code=payload.code)


@router.post("/redeem", response_model=RedeemExecuteResponse)
@limiter.limit("10/minute")
async def execute_redemption_code(
    payload: RedeemExecuteRequest,
    request: Request,
    user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RedeemExecuteResponse:
    return await svc.redeem_code(
        db,
        user=user,
        raw_code=payload.code,
        target_server_id=payload.target_server_id,
    )
