"""实际交付完成后向网关确认；未确认的付款由定时任务补发。"""

import logging

from sqlalchemy import select

from app.core.time import utc_naive_now
from app.db.models.billing import BillingOrder, BillingPayment
from app.db.session import get_session_factory
from app.services.billing.gateway_client import GatewayClient, GatewayError

logger = logging.getLogger(__name__)


async def report_deliveries() -> None:
    factory = get_session_factory()
    async with factory() as db:
        ids = list((await db.scalars(select(BillingPayment.id).join(BillingOrder).where(
            BillingOrder.applied_at.is_not(None), BillingPayment.status == "paid",
            BillingPayment.delivery_confirmed_at.is_(None),
        ).limit(100))).all())
    for payment_id in ids:
        async with factory() as db:
            payment = (await db.scalars(select(BillingPayment).where(BillingPayment.id == payment_id))).one()
            client = await GatewayClient.load(db)
            gateway_id = payment.gateway_id
            await db.commit()
            try:
                await client.request("POST", f"/api/v1/payments/{gateway_id}/delivery")
            except GatewayError as exc:
                logger.warning("交付确认待补发，payment=%s: %s", payment_id, exc)
                continue
            payment.delivery_confirmed_at = utc_naive_now()
            await db.commit()
