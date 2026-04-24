"""Admin endpoint for the three global monitoring defaults that survive
after the per-host alert refactor: collection interval, retention
window, and default alert-email recipient list.

All three live in ``manager_system_settings`` and are registered in
``MONITORING_SPECS``. They are exposed here under ``/api/admin/global-defaults``
as a friendlier, purpose-built surface for PR-C's "Global defaults"
modal; the legacy ``/api/admin/monitoring-settings`` route still works
for backwards compatibility.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.runtime_settings import MONITORING_SPECS, defaults_for
from app.core.settings_store import get_settings_store
from app.db.models.pterodactyl import PteroUser
from app.services.audit import log_manager_activity

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/global-defaults", tags=["admin-global-defaults"])


class GlobalDefaultsOut(BaseModel):
    monitor_interval_sec: int
    monitor_retention_days: int
    alert_default_recipients: list[int]


class GlobalDefaultsIn(BaseModel):
    monitor_interval_sec: int | None = Field(default=None, ge=30, le=3600)
    monitor_retention_days: int | None = Field(default=None, ge=1, le=365)
    alert_default_recipients: list[int] | None = None


def _parse_recipients(raw: Any) -> list[int]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [int(x) for x in raw if str(x).isdigit()]
    return [int(x) for x in str(raw).split(",") if x.strip().isdigit()]


@router.get("", response_model=GlobalDefaultsOut)
async def get_global_defaults(
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> GlobalDefaultsOut:
    store = get_settings_store()
    values = await store.get_many(db, defaults_for(MONITORING_SPECS))
    return GlobalDefaultsOut(
        monitor_interval_sec=int(values.get("MONITOR_INTERVAL_SEC") or 60),
        monitor_retention_days=int(values.get("MONITOR_RETENTION_DAYS") or 30),
        alert_default_recipients=_parse_recipients(values.get("ALERT_DEFAULT_RECIPIENTS")),
    )


@router.put("", response_model=GlobalDefaultsOut)
async def put_global_defaults(
    body: GlobalDefaultsIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> GlobalDefaultsOut:
    store = get_settings_store()

    updates: dict[str, Any] = {}
    if body.monitor_interval_sec is not None:
        updates["MONITOR_INTERVAL_SEC"] = body.monitor_interval_sec
    if body.monitor_retention_days is not None:
        updates["MONITOR_RETENTION_DAYS"] = body.monitor_retention_days
    if body.alert_default_recipients is not None:
        updates["ALERT_DEFAULT_RECIPIENTS"] = ",".join(
            str(x) for x in body.alert_default_recipients
        )

    normalized: dict[str, Any] = {}
    for key, value in updates.items():
        spec = MONITORING_SPECS.get(key)
        if spec is None:
            continue
        try:
            normalized[key] = spec.normalize(value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
            ) from exc

    if normalized:
        await store.set_values(db, normalized, category="monitoring", commit=False)
        await db.commit()

    await log_manager_activity(
        db, actor=admin.username, action="global_defaults_update", status="success",
        detail_key="global_defaults.update",
        detail_params={"keys": sorted(normalized.keys())},
    )

    return await get_global_defaults(_admin=admin, db=db)  # type: ignore[arg-type]
