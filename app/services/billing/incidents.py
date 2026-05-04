"""Incident logger — writes to ``manager_billing_incidents`` in its own
session so callers' open transactions never block on best-effort audit.

See ``docs/BILLING_DESIGN.md`` §1 (I5) and §3.10. ``log_incident`` is the
single sanctioned entry point for raising operator-visible billing events;
it never raises (failures are logged and swallowed) and runs in an
independent DB session to satisfy I4 ("external/audit writes outside
business transactions").

Signal-vs-noise rule: only call this for situations a human operator
must look at. Routine validation failures stay in API 4xx responses.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from app.core.time import utc_naive_now
from app.db.models.billing import BillingIncident
from app.db.session import get_session_factory

logger = logging.getLogger(__name__)


# Mirrors the ENUM in 0012_billing.py; surfaced here so type checkers catch
# typos at call sites without importing the model.
IncidentKind = str  # one of INCIDENT_KIND_VALUES — keep in sync with model


async def log_incident(
    kind: IncidentKind,
    *,
    payload: Mapping[str, Any],
    order_id: int | None = None,
    invoice_id: int | None = None,
    transaction_id: int | None = None,
    server_id: int | None = None,
) -> None:
    """Persist an incident row in an independent session.

    Best-effort: a write failure is logged and swallowed — the caller's
    business decision (e.g. order moved to ``manual_review``) is the
    primary safeguard, the incident row is just the operator inbox.
    """
    factory = get_session_factory()
    try:
        async with factory() as session:
            session.add(
                BillingIncident(
                    kind=kind,
                    order_id=order_id,
                    invoice_id=invoice_id,
                    transaction_id=transaction_id,
                    server_id=server_id,
                    payload=dict(payload),
                    detected_at=utc_naive_now(),
                )
            )
            await session.commit()
    except Exception:
        logger.exception(
            "log_incident failed kind=%s order_id=%s invoice_id=%s",
            kind,
            order_id,
            invoice_id,
        )
