"""User-facing payment gateway listing.

Returns a curated list of currently active payment gateways for the cashier
modal. ``display_name`` is sourced from runtime settings (admin-editable) so
end users never see vendor brand names like "虎皮椒".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.core.runtime_settings import BILLING_SPECS, defaults_for
from app.core.settings_store import get_settings_store
from app.db.models.pterodactyl import PteroUser
from app.services.billing.gateway import registry as gateway_registry

router = APIRouter(prefix="/user/payment-gateways", tags=["billing"])


# Per-gateway icon (vendor wallet style is fixed).
# display_name is admin-editable via ``<CODE_UPPER>_DISPLAY_NAME`` setting.
_GATEWAY_ICON: dict[str, str] = {
    "hupijiao": "qr_code_2",
}

_FALLBACK_DISPLAY_NAME = "在线支付"
_FALLBACK_ICON = "payments"


class PaymentGatewayOut(BaseModel):
    code: str
    display_name: str
    icon_name: str


@router.get("", response_model=list[PaymentGatewayOut])
async def list_payment_gateways(
    _user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PaymentGatewayOut]:
    await gateway_registry.ensure_loaded(db)
    store = get_settings_store()
    billing = await store.get_many(db, defaults_for(BILLING_SPECS))

    out: list[PaymentGatewayOut] = []
    for gw in gateway_registry.all_active():
        display_key = f"{gw.code.upper()}_DISPLAY_NAME"
        display_name = (
            (billing.get(display_key) or "").strip() or _FALLBACK_DISPLAY_NAME
        )
        icon_name = _GATEWAY_ICON.get(gw.code, _FALLBACK_ICON)
        out.append(
            PaymentGatewayOut(
                code=gw.code,
                display_name=display_name,
                icon_name=icon_name,
            )
        )
    return out
