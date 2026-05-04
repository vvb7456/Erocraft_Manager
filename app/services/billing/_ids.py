"""Identifier generators for billing entities.

Format: ``<prefix><yyyymmddHHMMSS><RAND4>`` (UTC, naive).

Total length: 2 + 14 + 4 = 20 characters — well within the 32-char column.
The 4-char random suffix is uppercase alphanumerics ([A-Z0-9]) drawn from
``secrets.choice`` to keep collisions astronomically unlikely while still
being human-readable on invoices / refund slips.

Collisions resolve naturally via ``UNIQUE`` constraints on the columns
(``order_no`` / ``invoice_no`` / ``refund_no``); callers that hit an
``IntegrityError`` should regenerate and retry.
"""

from __future__ import annotations

import secrets
import string

from app.core.time import utc_naive_now

_ALPHABET = string.ascii_uppercase + string.digits


def _suffix(n: int = 4) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def _stamp() -> str:
    return utc_naive_now().strftime("%Y%m%d%H%M%S")


def gen_order_no() -> str:
    return f"EM{_stamp()}{_suffix()}"


def gen_invoice_no() -> str:
    return f"IN{_stamp()}{_suffix()}"


def gen_refund_no() -> str:
    return f"RF{_stamp()}{_suffix()}"
