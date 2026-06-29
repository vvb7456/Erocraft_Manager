"""In-memory registry of active payment gateway adapters.

Adapters are loaded **lazily from DB-backed runtime settings** the first
time anyone asks for one. Callers must ``await ensure_loaded(db)`` before
calling :func:`get` / :func:`all_active`. After admin updates billing
settings, call ``await ensure_loaded(db, force=True)`` to rebuild.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.services.billing.gateway.base import PaymentGateway

if TYPE_CHECKING:  # avoid circular at runtime
    from sqlalchemy.ext.asyncio import AsyncSession

_log = logging.getLogger(__name__)
_REGISTRY: dict[str, PaymentGateway] = {}
_loaded: bool = False
_lock = asyncio.Lock()


def register(gateway: PaymentGateway) -> None:
    _REGISTRY[gateway.code] = gateway


def get(code: str) -> PaymentGateway:
    try:
        return _REGISTRY[code]
    except KeyError as exc:
        raise KeyError(f"payment gateway not registered: {code!r}") from exc


def all_active() -> list[PaymentGateway]:
    return list(_REGISTRY.values())


def clear() -> None:
    """Test helper: drop all registered adapters."""
    global _loaded
    _REGISTRY.clear()
    _loaded = False


async def ensure_loaded(db: "AsyncSession", *, force: bool = False) -> None:
    """Build the in-memory registry from runtime settings.

    Cheap when already loaded. Pass ``force=True`` after admin edits billing
    settings to rebuild.
    """
    global _loaded
    if _loaded and not force:
        return
    async with _lock:
        if _loaded and not force:
            return
        # Local imports to avoid circulars at module import time.
        from app.core.runtime_settings import BILLING_SPECS, defaults_for
        from app.core.settings_store import get_settings_store
        from app.services.billing.gateway.hupijiao import HupijiaoGateway

        store = get_settings_store()
        values = await store.get_many(db, defaults_for(BILLING_SPECS))
        _REGISTRY.clear()

        if values.get("HUPIJIAO_ENABLED"):
            appid = (values.get("HUPIJIAO_APPID") or "").strip()
            secret = (values.get("HUPIJIAO_APPSECRET") or "").strip()
            if appid and secret:
                _REGISTRY["hupijiao"] = HupijiaoGateway(
                    appid=appid, app_secret=secret
                )
                _log.info("Registered payment gateway: hupijiao")
            else:
                _log.warning(
                    "HUPIJIAO_ENABLED=true but APPID/APPSECRET missing — gateway not registered"
                )

        if values.get("ALIPAY_DIRECT_ENABLED"):
            from app.services.billing.gateway.alipay_direct import AlipayDirectGateway

            appid = (values.get("ALIPAY_DIRECT_APPID") or "").strip()
            priv = (values.get("ALIPAY_DIRECT_APP_PRIVATE_KEY") or "").strip()
            pub = (values.get("ALIPAY_DIRECT_ALIPAY_PUBLIC_KEY") or "").strip()
            if appid and priv and pub:
                gw_url = (values.get("ALIPAY_DIRECT_GATEWAY") or "").strip()
                seller_id = (values.get("ALIPAY_DIRECT_SELLER_ID") or "").strip() or None
                _REGISTRY["alipay_direct"] = AlipayDirectGateway(
                    appid=appid,
                    app_private_key_pem=priv,
                    alipay_public_key_pem=pub,
                    gateway_url=gw_url,
                    seller_id=seller_id,
                )
                _log.info("Registered payment gateway: alipay_direct")
            else:
                _log.warning(
                    "ALIPAY_DIRECT_ENABLED=true but APPID/PRIVATE_KEY/PUBLIC_KEY "
                    "missing — gateway not registered"
                )
        _loaded = True
