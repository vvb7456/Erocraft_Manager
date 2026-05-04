"""Operations CLI — surface unmatched / unprocessed payment events.

See ``BILLING_DESIGN.md`` §11.6 / §16 for context. When a webhook arrives
for an invoice that the system can't match (rare race: webhook beat the
order's first commit, or the invoice was deleted, or the gateway sent
a stale event), it is still persisted in
``manager_billing_payment_events`` with ``signature_ok=true`` but no
``invoice_id`` resolved.

This script does **not** mutate any rows — operators must decide per
event whether to:

1. Manually create a matching invoice + ``add_payment`` (rare; only when
   the user has clearly paid for an order we lost), or
2. Mark the event as a stray and refund the payer offline.

Run::

    /opt/erocraft_manager/venv/bin/python \\
        -m app.scripts.billing_recover_unknown_payment

Optional filters::

    --gateway hupijiao        only this gateway
    --since 2026-04-01        only events received on/after date (UTC)
    --include-processed       also list events with non-null process_result

Output is human-readable to stdout; capture with ``| tee report.txt``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select

from app.db.models.billing import BillingInvoice, BillingPaymentEvent
from app.db.session import dispose_engine, get_session_factory


def _parse_date(s: str) -> datetime:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid date {s!r}; expected YYYY-MM-DD"
        ) from exc


def _short_body(raw: str, *, limit: int = 240) -> str:
    """Try to JSON-pretty the first ``limit`` chars of the body."""
    try:
        obj = json.loads(raw)
        pretty = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    except json.JSONDecodeError:
        pretty = raw
    if len(pretty) > limit:
        return pretty[:limit] + " …(truncated)"
    return pretty


async def _fetch_events(
    *,
    gateway: str | None,
    since: datetime | None,
    include_processed: bool,
) -> list[BillingPaymentEvent]:
    factory = get_session_factory()
    async with factory() as session:
        # Default: signature OK + (invoice_id IS NULL OR process_result indicates no match)
        # With --include-processed: also surface events that were processed but where
        # invoice_id is still NULL (they should have been investigated already).
        bad_results = ("no_invoice_match", "unknown", "skipped", "duplicate")
        if include_processed:
            cond = or_(
                BillingPaymentEvent.invoice_id.is_(None),
                BillingPaymentEvent.process_result.in_(bad_results),
            )
        else:
            cond = and_(
                BillingPaymentEvent.signature_ok.is_(True),
                or_(
                    BillingPaymentEvent.invoice_id.is_(None),
                    BillingPaymentEvent.process_result.is_(None),
                    BillingPaymentEvent.process_result.in_(bad_results),
                ),
            )
        stmt = select(BillingPaymentEvent).where(cond).order_by(
            BillingPaymentEvent.received_at.asc()
        )
        if gateway:
            stmt = stmt.where(BillingPaymentEvent.gateway_code == gateway)
        if since is not None:
            stmt = stmt.where(BillingPaymentEvent.received_at >= since)
        rows = (await session.execute(stmt)).scalars().all()

        # For each row, attempt a soft "did this transaction_id ever match
        # a real invoice afterwards?" lookup so the report flags clearly
        # orphaned vs. eventually-processed cases.
        for ev in rows:
            ev.__dict__["_followup_invoice_no"] = None
            if ev.invoice_id is not None:
                inv = await session.get(BillingInvoice, ev.invoice_id)
                if inv is not None:
                    ev.__dict__["_followup_invoice_no"] = inv.invoice_no
        return list(rows)


def _print_report(events: list[BillingPaymentEvent]) -> None:
    if not events:
        print("OK: no unmatched / unprocessed payment events found.")
        return
    print(f"Found {len(events)} payment event(s) needing operator review.\n")
    for ev in events:
        followup = ev.__dict__.get("_followup_invoice_no")
        sig = "yes" if ev.signature_ok else "NO (rejected)"
        print(
            f"--- event id={ev.id}  gateway={ev.gateway_code}  "
            f"type={ev.event_type}"
        )
        print(f"  received_at  : {ev.received_at.isoformat()}Z")
        print(f"  signature_ok : {sig}")
        print(f"  invoice_id   : {ev.invoice_id}  (followup={followup})")
        print(f"  transaction  : {ev.transaction_id}")
        print(f"  processed_at : {ev.processed_at.isoformat() + 'Z' if ev.processed_at else '(never)'}")
        print(f"  process_res  : {ev.process_result!r}")
        print(f"  raw_body[..240]: {_short_body(ev.raw_body)}")
        print()
    print(
        "Next steps: cross-check each event against the gateway dashboard. "
        "If the payer is identifiable and the order can be reconstructed, "
        "manually create the invoice + call billing.payments.add_payment(); "
        "otherwise initiate an offline refund and annotate the event in "
        "manager_billing_incidents."
    )


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="billing_recover_unknown_payment",
        description=(
            "Read-only report of payment-gateway webhooks that did not "
            "match a billing invoice. Operators triage manually."
        ),
    )
    parser.add_argument("--gateway", help="filter by gateway_code (e.g. hupijiao)")
    parser.add_argument("--since", type=_parse_date, help="YYYY-MM-DD lower bound (UTC)")
    parser.add_argument(
        "--include-processed",
        action="store_true",
        help="also include events with non-null process_result that still have no invoice_id",
    )
    args = parser.parse_args(argv)

    try:
        events = await _fetch_events(
            gateway=args.gateway,
            since=args.since,
            include_processed=args.include_processed,
        )
    finally:
        await dispose_engine()

    _print_report(events)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))
