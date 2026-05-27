"""Referral reward orchestration.

See ``docs/REFERRAL_AND_COUPON_DESIGN.md`` §5.

Two-phase grant (so the invitee can actually use their welcome coupon
on their *first* paid order):

* **At registration** (``register_verify`` in ``api.routers.public``):
  create the ``UserReferral(status='registered')`` row and immediately
  issue the invitee's welcome coupon. Email the invitee.
* **At the invitee's first qualifying applied order**
  (``try_grant_for_order`` below): issue the inviter's reward coupon,
  mark referral ``rewarded``, email the inviter. If the invitee coupon
  was *not* issued at registration (template was misconfigured at the
  time), issue it now as a degraded-mode fallback and email the invitee.

Idempotency: ``with_for_update`` on the referral row plus a status
guard mean repeated post-action calls (apply_engine retries) are no-ops.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime_settings import BILLING_SPECS
from app.core.settings_store import get_settings_store
from app.core.time import utc_naive_now
from app.db.models.billing import BillingOrder, Coupon, CouponTemplate
from app.db.models.manager import UserReferral
from app.db.models.pterodactyl import PteroUser
from app.services.billing import coupons as coupon_service

logger = logging.getLogger(__name__)


async def _runtime(db: AsyncSession, key: str) -> Any:
    spec = BILLING_SPECS[key]
    return await get_settings_store().get(db, key, spec.default_value())


async def _resolve_template(
    db: AsyncSession, code: str
) -> CouponTemplate | None:
    if not code:
        return None
    return (
        await db.execute(
            select(CouponTemplate).where(
                CouponTemplate.code == code,
                CouponTemplate.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()


_DEFAULT_QUALIFYING_KINDS = ("new_purchase", "renew", "upgrade")


async def _qualifying_kinds(db: AsyncSession) -> tuple[str, ...]:
    raw = await _runtime(db, "REFERRAL_QUALIFYING_KINDS")
    if isinstance(raw, list):
        items = tuple(str(k).strip() for k in raw if str(k).strip())
    else:
        items = ()
    return items or _DEFAULT_QUALIFYING_KINDS


async def try_grant_for_order(
    db: AsyncSession, order: BillingOrder
) -> UserReferral | None:
    """Best-effort: grant paired referral coupons for ``order`` if eligible.

    Returns the updated ``UserReferral`` row on success, ``None`` if
    nothing was granted (most calls — only the *first* qualifying order
    per invitee triggers a grant). Never raises into the caller —
    apply_engine's main flow must not be blocked by a referral hiccup.
    """
    try:
        return await _try_grant_inner(db, order)
    except Exception:  # noqa: BLE001 — defensive; never break apply flow
        logger.exception(
            "referral_rewards: grant failed for order_id=%s", order.id
        )
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def _try_grant_inner(
    db: AsyncSession, order: BillingOrder
) -> UserReferral | None:
    if order.status != "applied":
        return None

    enabled = bool(await _runtime(db, "REFERRAL_REWARD_ENABLED"))
    if not enabled:
        return None

    qualifying_kinds = await _qualifying_kinds(db)
    if order.kind not in qualifying_kinds:
        return None

    min_fen = int(await _runtime(db, "REFERRAL_QUALIFYING_MIN_FEN"))
    # Compare against ``total_fen`` (payable, post-coupon) per design
    # doc §6.6 — the order's pricing tier, not actual cash received.
    # An order whose coupon brings ``total_fen`` to 0 will not qualify,
    # which prevents the reward-coupon-chain abuse vector.
    if (order.total_fen or 0) < min_fen:
        return None

    # Find a pending referral for this invitee.
    referral = (
        await db.execute(
            select(UserReferral).where(
                UserReferral.invitee_user_id == order.user_id,
                UserReferral.status == "registered",
            )
        )
    ).scalar_one_or_none()
    if referral is None:
        return None  # no referral, already rewarded, or revoked

    inviter_code = str(await _runtime(db, "REFERRAL_INVITER_TEMPLATE_CODE"))
    invitee_code = str(await _runtime(db, "REFERRAL_INVITEE_TEMPLATE_CODE"))
    inviter_tpl = await _resolve_template(db, inviter_code)
    invitee_tpl = await _resolve_template(db, invitee_code)
    if inviter_tpl is None or invitee_tpl is None:
        logger.warning(
            "referral_rewards: template missing (inviter=%s, invitee=%s); skipping",
            inviter_code, invitee_code,
        )
        # Surface to ops via the manager activity log (incident table
        # ENUM doesn't include a referral kind — the activity log is
        # the lighter-weight operator inbox we already use for similar
        # config-drift signals).
        try:
            from app.services.audit import log_manager_activity
            await log_manager_activity(
                db,
                actor="system",
                category="billing",
                status="info",
                detail_key="billing.referral.template_missing",
                detail_params={
                    "order_id": order.id,
                    "inviter_code": inviter_code,
                    "invitee_code": invitee_code,
                },
            )
        except Exception:
            logger.exception(
                "referral_rewards: activity log for template_missing failed"
            )
        return None

    # Reload with FOR UPDATE so two concurrent applies (impossible by
    # design but cheap insurance) can't both grant.
    locked = (
        await db.execute(
            select(UserReferral)
            .where(UserReferral.id == referral.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if locked is None or locked.status != "registered":
        return None

    now = utc_naive_now()
    inviter_coupon = await coupon_service.issue_from_template(
        db,
        user_id=locked.inviter_user_id,
        template=inviter_tpl,
        source="referral_inviter",
        source_ref_id=locked.id,
        commit=False,
    )
    # Invitee coupon: prefer the one issued at registration. If the
    # template was misconfigured at registration time we issue it now
    # as a degraded-mode fallback so the invitee isn't left empty-handed.
    invitee_coupon_was_new = False
    if locked.invitee_coupon_id:
        invitee_coupon = await db.get(Coupon, locked.invitee_coupon_id)
    else:
        invitee_coupon = await coupon_service.issue_from_template(
            db,
            user_id=locked.invitee_user_id,
            template=invitee_tpl,
            source="referral_invitee",
            source_ref_id=locked.id,
            commit=False,
        )
        invitee_coupon_was_new = True
        locked.invitee_coupon_id = invitee_coupon.id

    locked.status = "rewarded"
    locked.rewarded_at = now
    locked.qualifying_order_id = order.id
    locked.inviter_coupon_id = inviter_coupon.id
    await db.commit()
    await db.refresh(locked)

    # Surface to ops via activity log so reward issuance is auditable
    # alongside the manual grant/revoke entries.
    try:
        from app.services.audit import log_manager_activity
        await log_manager_activity(
            db,
            actor="system",
            category="billing",
            status="success",
            detail_key="billing.referral.rewarded",
            detail_params={
                "order_id": order.id,
                "referral_id": locked.id,
                "inviter_user_id": locked.inviter_user_id,
                "invitee_user_id": locked.invitee_user_id,
                "inviter_coupon_id": inviter_coupon.id,
                "invitee_coupon_id": invitee_coupon.id,
            },
        )
    except Exception:
        logger.exception("referral_rewards: activity log for rewarded failed")

    # Best-effort email notifications — outside the critical tx. The
    # invitee was already emailed at registration when their coupon was
    # issued there; only re-email if we just issued it in fallback mode.
    await _notify(
        db,
        locked,
        inviter_coupon,
        invitee_coupon,
        order,
        notify_invitee=invitee_coupon_was_new,
    )
    return locked


async def _notify(
    db: AsyncSession,
    referral: UserReferral,
    inviter_coupon: Coupon,
    invitee_coupon: Coupon,
    order: BillingOrder,
    *,
    notify_invitee: bool = True,
) -> None:
    """Send reward emails. Swallows all errors — emails are best-effort."""
    try:
        from app.core.settings_store import get_settings_store
        from app.core.runtime_settings import SETTINGS_SPECS
        from app.services.email import (
            get_site_url,
            load_template,
            render_template_body,
            send_email,
        )
    except ImportError:
        return

    try:
        inviter = await db.get(PteroUser, referral.inviter_user_id)
        invitee = await db.get(PteroUser, referral.invitee_user_id)
    except Exception:
        logger.exception("referral_rewards: user load for email failed")
        return

    def _fmt_yuan(fen: int) -> str:
        return f"{fen / 100:.2f}"

    def _min_order_text(fen: int) -> str:
        return "无门槛" if fen <= 0 else f"订单满 ¥{_fmt_yuan(fen)} 可用"

    # Load templates (for coupon_name in email body) — best effort.
    try:
        from app.db.models.billing import CouponTemplate
        inviter_tpl = await db.get(CouponTemplate, inviter_coupon.template_id)
        invitee_tpl = await db.get(CouponTemplate, invitee_coupon.template_id)
    except Exception:
        inviter_tpl = invitee_tpl = None

    store = get_settings_store()
    brand_name = str(
        await store.get(
            db, "BRAND_NAME", SETTINGS_SPECS["BRAND_NAME"].default_value()
        )
    )
    site_url = await get_site_url(db) or None

    async def _send_one(
        *,
        template_type: str,
        recipient: PteroUser | None,
        params: dict[str, Any],
    ) -> None:
        if recipient is None or not recipient.email:
            return
        try:
            tpl = await load_template(db, template_type)
        except Exception:
            logger.exception(
                "referral_rewards: template %s missing", template_type
            )
            return
        try:
            subject, body = render_template_body(tpl, params)
        except Exception:
            logger.exception(
                "referral_rewards: template %s render failed", template_type
            )
            return
        try:
            await send_email(
                db,
                recipient_email=recipient.email,
                subject=subject,
                main_content_raw=body,
                greeting=f"亲爱的 {recipient.username}",
                action_text="查看我的优惠券" if site_url else None,
                action_url=f"{site_url}/#/account" if site_url else None,
                actor="system",
            )
        except Exception:
            logger.exception(
                "referral_rewards: %s email send failed (user=%s)",
                template_type, recipient.id,
            )

    await _send_one(
        template_type="referral_inviter_rewarded",
        recipient=inviter,
        params={
            "brand_name": brand_name,
            "username": inviter.username if inviter else "",
            "invitee_username": invitee.username if invitee else "",
            "coupon_code": inviter_coupon.code,
            "coupon_name": inviter_tpl.name if inviter_tpl else "邀请奖励券",
            "discount_yuan": _fmt_yuan(inviter_coupon.discount_fen),
            "min_order_yuan": _fmt_yuan(inviter_coupon.min_order_fen),
            "min_order_text": _min_order_text(inviter_coupon.min_order_fen),
            "expires_at": inviter_coupon.expires_at.strftime("%Y-%m-%d"),
        },
    )
    if not notify_invitee:
        return
    await _send_one(
        template_type="referral_invitee_rewarded",
        recipient=invitee,
        params={
            "brand_name": brand_name,
            "username": invitee.username if invitee else "",
            "coupon_code": invitee_coupon.code,
            "coupon_name": invitee_tpl.name if invitee_tpl else "新人欢迎券",
            "discount_yuan": _fmt_yuan(invitee_coupon.discount_fen),
            "min_order_yuan": _fmt_yuan(invitee_coupon.min_order_fen),
            "min_order_text": _min_order_text(invitee_coupon.min_order_fen),
            "expires_at": invitee_coupon.expires_at.strftime("%Y-%m-%d"),
        },
    )


async def send_invitee_welcome_email(
    db: AsyncSession,
    *,
    invitee_user_id: int,
    coupon: Coupon,
) -> None:
    """Email the invitee the welcome-coupon details immediately after
    registration. Best-effort; swallows all exceptions.
    """
    try:
        from app.core.runtime_settings import SETTINGS_SPECS
        from app.db.models.billing import CouponTemplate
        from app.services.email import (
            get_site_url,
            load_template,
            render_template_body,
            send_email,
        )

        invitee = await db.get(PteroUser, invitee_user_id)
        if invitee is None or not invitee.email:
            return
        tpl_row = await db.get(CouponTemplate, coupon.template_id)
        store = get_settings_store()
        brand_name = str(
            await store.get(
                db, "BRAND_NAME", SETTINGS_SPECS["BRAND_NAME"].default_value()
            )
        )
        site_url = await get_site_url(db) or None
        tpl = await load_template(db, "referral_invitee_rewarded")
        subject, body = render_template_body(
            tpl,
            {
                "brand_name": brand_name,
                "username": invitee.username,
                "coupon_code": coupon.code,
                "coupon_name": tpl_row.name if tpl_row else "新人欢迎券",
                "discount_yuan": f"{coupon.discount_fen / 100:.2f}",
                "min_order_yuan": f"{coupon.min_order_fen / 100:.2f}",
                "min_order_text": (
                    "无门槛"
                    if coupon.min_order_fen <= 0
                    else f"订单满 ¥{coupon.min_order_fen / 100:.2f} 可用"
                ),
                "expires_at": coupon.expires_at.strftime("%Y-%m-%d"),
            },
        )
        await send_email(
            db,
            recipient_email=invitee.email,
            subject=subject,
            main_content_raw=body,
            greeting=f"亲爱的 {invitee.username}",
            action_text="查看我的优惠券" if site_url else None,
            action_url=f"{site_url}/#/account" if site_url else None,
            actor="system",
        )
    except Exception:
        logger.exception(
            "send_invitee_welcome_email failed (user=%s)", invitee_user_id
        )
