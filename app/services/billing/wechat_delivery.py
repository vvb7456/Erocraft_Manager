"""Report mini program fulfillment only after the website actually applies an order."""

import logging
import secrets
import time
from datetime import timedelta, timezone

from sqlalchemy import func, or_, select, update

from app.core.runtime_settings import BILLING_SPECS, defaults_for
from app.core.settings_store import get_settings_store
from app.core.time import utc_naive_now
from app.db.models.billing import BillingInvoice, BillingOrder
from app.db.session import get_session_factory
from app.services import wechat_client
from app.services.billing import incidents
from app.services.billing.gateway.base import GatewayBusinessError

logger = logging.getLogger(__name__)


async def report_deliveries() -> None:
    factory = get_session_factory()
    async with factory() as db:
        ids = list((await db.scalars(select(BillingInvoice.id).join(BillingOrder, BillingOrder.id == BillingInvoice.order_id).where(
            BillingInvoice.gateway_code == "wechat_pay", BillingOrder.status == "applied",
            BillingInvoice.gateway_payload["scene"].as_string() == "miniprogram",
            func.coalesce(BillingInvoice.gateway_payload["delivery_reported"].as_boolean(), False).is_(False),
            func.coalesce(BillingInvoice.gateway_payload["delivery_next_at"].as_integer(), 0) <= int(time.time()),
        ).limit(20))).all())
    for iid in ids:
        async with factory() as db:
            invoice = await db.get(BillingInvoice, iid)
            assert invoice is not None
            oid = invoice.order_id
            lease, now = secrets.token_hex(16), utc_naive_now()
            claimed = await db.execute(update(BillingOrder).where(
                BillingOrder.id == oid, BillingOrder.status == "applied",
                or_(BillingOrder.lock_token.is_(None), BillingOrder.locked_until < now),
            ).values(lock_token=lease, locked_until=now + timedelta(minutes=2)))
            await db.commit()
            if not claimed.rowcount:
                continue
            saved = dict(invoice.gateway_payload or {})
            try:
                values = await get_settings_store().get_many(db, defaults_for(BILLING_SPECS))
                body = saved["request"]
                appid = values["WECHAT_PAY_MINIPROGRAM_APPID"]
                secret = values["WECHAT_PAY_MINIPROGRAM_APP_SECRET"]
                if appid != body["appid"]:
                    raise GatewayBusinessError("付款小程序AppID已变更，无法上报原订单交付信息")
                # A timed-out upload may already have succeeded. Query first so a
                # retry never consumes WeChat's single re-shipment allowance.
                remote = await wechat_client.account_request("mini", appid, secret, "/wxa/sec/order/get_order", {
                    "merchant_id": body["mchid"], "merchant_trade_no": invoice.invoice_no,
                })
                state = remote["order"]
                if not state.get("shipping", {}).get("finish_shipping") and state.get("order_state") not in (3, 4, 5):
                    await wechat_client.account_request("mini", appid, secret, "/wxa/sec/order/upload_shipping_info", {
                        "order_key": {"order_number_type": 1, "mchid": body["mchid"], "out_trade_no": invoice.invoice_no},
                        "logistics_type": 3, "delivery_mode": 1,
                        "shipping_list": [{"item_desc": body["description"][:120]}],
                        "upload_time": now.replace(tzinfo=timezone.utc).isoformat(), "payer": body["payer"],
                    })
                saved["delivery_reported"] = True
                saved.pop("delivery_error", None)
            except Exception as exc:
                logger.warning("小程序交付上报失败，稍后重试，invoice=%s: %s", iid, exc)
                saved["delivery_next_at"] = int(time.time()) + 300
                saved["delivery_error"] = str(exc)[:300]
                if not saved.get("delivery_incident"):
                    await incidents.log_incident("manual_review_required", order_id=oid, invoice_id=iid,
                                                 payload={"subkind": "wechat_delivery_report_failed", "error": str(exc)[:300]})
                    saved["delivery_incident"] = True
            finally:
                await db.execute(update(BillingInvoice).where(BillingInvoice.id == iid).values(gateway_payload=saved))
                await db.execute(update(BillingOrder).where(BillingOrder.id == oid, BillingOrder.lock_token == lease).values(lock_token=None, locked_until=None))
                await db.commit()
