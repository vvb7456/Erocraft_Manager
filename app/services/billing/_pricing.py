"""Pure pricing helpers shared between the order-creation path and the
upgrade-options preview endpoint.

Why this module exists
----------------------
Two places used to inline the same prorated-upgrade arithmetic:

* ``app/services/billing/orders.py`` — when actually creating an upgrade
  order (the user is charged this amount).
* ``app/api/routers/user_servers.py`` — the upgrade-options preview the
  frontend lists in the modal.

Any drift between the two — in remaining-day floor, per-day rounding, or
truncation direction — silently breaks the invariant that the modal's
displayed amount equals what the user is charged. Centralising the
formula here makes the contract explicit and unique.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol


class _PlanLike(Protocol):
    price_fen: int
    days: int


def remaining_billable_days(expiration_date: date | None, today: date) -> int:
    """Return the day count used for upgrade proration.

    Floors at ``1`` so a user upgrading on the very last day still pays
    something — never zero, never negative. Pre-expiration servers are
    rejected upstream; this helper isn't meant to *decide* eligibility,
    only to size the proration window.
    """
    if expiration_date is None:
        return 1
    return max((expiration_date - today).days, 1)


def upgrade_diff_fen(
    old_plan: _PlanLike,
    new_plan: _PlanLike,
    remaining_days: int,
) -> int:
    """Compute the prorated upgrade fee in fen.

    Formula: ``(new_price/new_days - old_price/old_days) * remaining_days``,
    truncated to int. Returns ``<= 0`` when the new plan is cheaper per
    day than the old one — callers should reject that as an invalid
    upgrade target.
    """
    new_per_day = Decimal(str(new_plan.price_fen)) / Decimal(str(new_plan.days))
    old_per_day = Decimal(str(old_plan.price_fen)) / Decimal(str(old_plan.days))
    return int((new_per_day - old_per_day) * Decimal(str(remaining_days)))
