"""Port-expression parser used by the admin allocation endpoints.

Supports comma-separated tokens, each of which is either a single port
``8000`` or an inclusive range ``8000-8010``. Whitespace is ignored. The
parser does **not** cap the resulting set size — operators are trusted
to type sensible numbers (per design decision in
``docs/HOST_ALLOCATIONS_DESIGN.md`` §2.4).
"""

from __future__ import annotations

import re

PORT_MIN = 1
PORT_MAX = 65535

_TOKEN_RE = re.compile(r"^(\d+)(?:-(\d+))?$")


class PortExpressionError(ValueError):
    """Raised when a port expression is syntactically or semantically invalid."""


def parse_port_expression(expr: str) -> set[int]:
    """Parse ``"8000,8005-8010,9000"`` → ``{8000, 8005..8010, 9000}``.

    Raises :class:`PortExpressionError` on any malformed token, out-of-range
    value, or reversed range.
    """
    if not isinstance(expr, str):  # pragma: no cover — pydantic guards this
        raise PortExpressionError("port expression must be a string")

    cleaned = expr.strip()
    if not cleaned:
        raise PortExpressionError("port expression is empty")

    ports: set[int] = set()
    for raw in cleaned.split(","):
        token = raw.strip()
        if not token:
            raise PortExpressionError(f"empty token in: {expr!r}")

        m = _TOKEN_RE.match(token)
        if not m:
            raise PortExpressionError(f"invalid token: {token!r}")

        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start

        if start < PORT_MIN or end > PORT_MAX:
            raise PortExpressionError(
                f"port out of range [{PORT_MIN}, {PORT_MAX}]: {token!r}"
            )
        if end < start:
            raise PortExpressionError(f"reversed range: {token!r}")

        ports.update(range(start, end + 1))

    return ports
