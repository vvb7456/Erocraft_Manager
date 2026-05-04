"""Billing email notifications — see ``BILLING_DESIGN.md`` §14.

Four template kinds, all best-effort (failures logged, never raised):

* ``orderPaid``        — user, after apply success
* ``orderApplyFailed`` — user, after retries exhausted (apply_failed)
* ``orderApplyAlert``  — admin(s), on first retry failure or apply_failed
* ``orderRefunded``    — user, after refund SUCCEEDED (full or partial)

Each notification runs in its own session via :func:`get_session_factory`
so it never participates in (and cannot rollback) the caller's billing
transaction. SMTP/template errors are swallowed and logged.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.core.runtime_settings import SETTINGS_SPECS
from app.core.settings_store import get_settings_store
from app.core.time import utc_naive_now
from app.db.models.billing import BillingOrder, BillingRefund
from app.db.models.pterodactyl import PteroUser
from app.db.session import get_session_factory
from app.services.email import (
    EmailTemplate,
    SiteUrlNotConfiguredError,
    load_template,
    render_template_body,
    send_email,
)

logger = logging.getLogger(__name__)

# ── Template key constants (internal keys; see email.py mapping) ──
KIND_ORDER_PAID = "order_paid"
KIND_ORDER_APPLY_FAILED = "order_apply_failed"
KIND_ORDER_APPLY_ALERT = "order_apply_alert"
KIND_ORDER_REFUNDED = "order_refunded"

_USER_KIND_GREETING = {
    KIND_ORDER_PAID: ("查看服务器", "/#/servers"),
    KIND_ORDER_APPLY_FAILED: (None, None),
    KIND_ORDER_REFUNDED: ("查看订单", "/#/account"),
}
_ADMIN_KIND_ACTION = {
    KIND_ORDER_APPLY_ALERT: ("查看订单", "/#/admin/billing/orders"),
}


def _fmt_dt(dt: Any) -> str:
    if dt is None:
        return ""
    try:
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:  # noqa: BLE001
        return str(dt)


def _yuan(fen: int | None) -> str:
    if fen is None:
        return ""
    return f"{fen / 100:.2f}"


async def _build_order_variables(
    db, order: BillingOrder, *, refund: BillingRefund | None = None
) -> dict[str, str]:
    snap = order.plan_snapshot or {}
    server_uuid = ""
    if order.target_server_id is not None:
        from app.db.models.pterodactyl import PteroServer

        srv = await db.scalar(
            select(PteroServer.uuid).where(PteroServer.id == order.target_server_id)
        )
        server_uuid = str(srv) if srv else ""

    brand_name = await get_settings_store().get(
        db, "BRAND_NAME", SETTINGS_SPECS["BRAND_NAME"].default_value()
    )

    variables: dict[str, str] = {
        "brand_name": str(brand_name),
        "order_no": order.order_no,
        "plan_name": str(snap.get("display_name") or snap.get("plan_name") or ""),
        "period_count": str(order.period_count),
        "total_days": str(order.total_days),
        "total_fen": str(order.total_fen),
        "total_yuan": _yuan(order.total_fen),
        "currency_code": str(snap.get("currency_code") or "CNY"),
        "paid_at": _fmt_dt(order.applied_at) if order.applied_at else _fmt_dt(order.updated_at),
        "applied_at": _fmt_dt(order.applied_at),
        "server_uuid": server_uuid,
        "apply_error": str(order.last_apply_error or ""),
        "apply_retry_count": str(order.apply_retry_count or 0),
    }
    if refund is not None:
        variables.update(
            {
                "refund_no": refund.refund_no,
                "refund_amount_fen": str(refund.amount_fen),
                "refund_amount_yuan": _yuan(refund.amount_fen),
                "refund_reason": str(refund.reason or ""),
                "refunded_at": _fmt_dt(refund.updated_at or utc_naive_now()),
            }
        )
    return variables


async def _resolve_user_email(db, user_id: int) -> tuple[str | None, str]:
    row = await db.execute(
        select(PteroUser.username, PteroUser.email).where(PteroUser.id == user_id)
    )
    res = row.first()
    if res is None:
        return None, ""
    return res.email, res.username or ""


async def _resolve_admin_recipients(db) -> list[tuple[str, str]]:
    rows = await db.execute(
        select(PteroUser.username, PteroUser.email).where(
            PteroUser.root_admin.is_(True)
        )
    )
    return [(u or "管理员", e) for (u, e) in rows.all() if e]


async def _send_one(
    db,
    *,
    template_key: str,
    recipient_email: str,
    greeting: str,
    variables: dict[str, str],
    action_text: str | None,
    action_url: str | None,
) -> None:
    template = await load_template(db, template_key)
    if not template.subject and not template.body:
        logger.warning("billing email template missing: %s", template_key)
        return
    subject, body = render_template_body(template, variables)
    ok, err = await send_email(
        db,
        recipient_email=recipient_email,
        subject=subject,
        main_content_raw=body,
        greeting=greeting,
        action_text=action_text,
        action_url=action_url,
        actor="system",
    )
    if not ok:
        logger.warning(
            "billing email send failed kind=%s to=%s: %s",
            template_key,
            recipient_email,
            err,
        )


async def _send_user_email(
    *,
    template_key: str,
    order_id: int,
    refund_id: int | None = None,
) -> None:
    """Independent-session sender for user-facing billing emails."""
    factory = get_session_factory()
    try:
        async with factory() as session:
            order = await session.get(BillingOrder, order_id)
            if order is None:
                logger.warning("billing email: order %s not found", order_id)
                return
            refund = None
            if refund_id is not None:
                refund = await session.get(BillingRefund, refund_id)
                if refund is None:
                    logger.warning("billing email: refund %s not found", refund_id)
                    return

            email, username = await _resolve_user_email(session, order.user_id)
            if not email:
                logger.warning(
                    "billing email: user %s has no email (order_id=%s)",
                    order.user_id,
                    order_id,
                )
                return

            site_url = ""
            try:
                from app.services.email import get_site_url

                site_url = await get_site_url(session)
            except SiteUrlNotConfiguredError:
                logger.warning(
                    "billing email skipped (SITE_URL not configured) kind=%s order_id=%s",
                    template_key,
                    order_id,
                )
                return

            variables = await _build_order_variables(session, order, refund=refund)
            action_text, action_path = _USER_KIND_GREETING.get(
                template_key, ("查看", "/")
            )
            await _send_one(
                session,
                template_key=template_key,
                recipient_email=email,
                greeting=f"您好，{username or '用户'}：",
                variables=variables,
                action_text=action_text,
                action_url=f"{site_url}{action_path}",
            )
    except Exception:
        logger.exception(
            "billing email send failed kind=%s order_id=%s", template_key, order_id
        )


async def _send_admin_alert(*, order_id: int) -> None:
    factory = get_session_factory()
    try:
        async with factory() as session:
            order = await session.get(BillingOrder, order_id)
            if order is None:
                return
            recipients = await _resolve_admin_recipients(session)
            if not recipients:
                logger.warning(
                    "billing admin alert: no root_admin recipients (order_id=%s)",
                    order_id,
                )
                return

            site_url = ""
            try:
                from app.services.email import get_site_url

                site_url = await get_site_url(session)
            except SiteUrlNotConfiguredError:
                logger.warning(
                    "billing admin alert skipped (SITE_URL not configured) order_id=%s",
                    order_id,
                )
                return

            user_email, username = await _resolve_user_email(session, order.user_id)
            variables = await _build_order_variables(session, order)
            variables["username"] = username or str(order.user_id)
            variables["email"] = user_email or ""

            action_text, action_path = _ADMIN_KIND_ACTION[KIND_ORDER_APPLY_ALERT]
            for admin_name, admin_email in recipients:
                await _send_one(
                    session,
                    template_key=KIND_ORDER_APPLY_ALERT,
                    recipient_email=admin_email,
                    greeting=f"管理员 {admin_name}：",
                    variables=variables,
                    action_text=action_text,
                    action_url=f"{site_url}{action_path}",
                )
    except Exception:
        logger.exception(
            "billing admin alert send failed order_id=%s", order_id
        )


# ── Public hooks (call sites in apply_engine.py / refunds.py) ──


async def notify_order_paid(order_id: int) -> None:
    """Apply succeeded — tell the user."""
    await _send_user_email(template_key=KIND_ORDER_PAID, order_id=order_id)


async def notify_order_apply_failed(order_id: int) -> None:
    """Retries exhausted (apply_failed) — tell the user."""
    await _send_user_email(template_key=KIND_ORDER_APPLY_FAILED, order_id=order_id)


async def notify_order_apply_alert(order_id: int) -> None:
    """First retry failure or terminal apply_failed — tell admins."""
    await _send_admin_alert(order_id=order_id)


async def notify_order_refunded(order_id: int, refund_id: int) -> None:
    """Refund SUCCEEDED — tell the user."""
    await _send_user_email(
        template_key=KIND_ORDER_REFUNDED,
        order_id=order_id,
        refund_id=refund_id,
    )
