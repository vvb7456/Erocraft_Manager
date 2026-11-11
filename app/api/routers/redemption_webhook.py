"""Agiso 91 卡券仓库 custom pull API webhook endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.db import get_db
from app.core.rate_limit import limiter
from app.schemas.redemption import AgisoIssueRequest, AgisoIssueResponse
from app.services.billing import redemption as svc

router = APIRouter(prefix="/webhook/redemption", tags=["billing"])


def _extract_api_token(request: Request) -> str | None:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    api_key = request.headers.get("x-api-key") or request.headers.get("x-redemption-token")
    if api_key:
        return api_key.strip()
    q_token = request.query_params.get("token") or request.query_params.get("api_key")
    if q_token:
        return q_token.strip()
    return None


@router.post("/issue", response_model=AgisoIssueResponse)
@limiter.limit("120/minute")
async def agiso_issue_codes(
    payload: AgisoIssueRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AgisoIssueResponse:
    token = _extract_api_token(request)
    await svc.verify_api_token(db, token)
    data = await svc.issue_via_agiso_api(db, payload)
    return AgisoIssueResponse(code=0, msg="ok", data=data)
