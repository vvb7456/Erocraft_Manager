"""Lightweight Origin / Referer check to mitigate CSRF.

Cookie-session POST/PATCH/PUT/DELETE requests must come from the same
origin (or have no Origin header at all — server-to-server callers from
trusted internal networks). For browser-driven requests this is the
de-facto industry baseline alongside SameSite=Lax cookies.

Rationale
---------
We rely on signed-cookie sessions, which are auto-attached by the browser
to any cross-origin POST. SameSite=Lax blocks most top-level cross-site
POSTs but does not protect XHR/fetch from a malicious page on a different
origin.  Comparing ``Origin`` (preferred) or ``Referer`` (fallback) against
the request's own host gives us a cheap second line of defence without the
ergonomic cost of CSRF tokens.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Reject state-changing requests whose Origin/Referer does not match Host."""

    async def dispatch(self, request: Request, call_next):
        if request.method not in UNSAFE_METHODS:
            return await call_next(request)

        host = request.headers.get("host", "").lower()
        if not host:
            # Without a Host header we can't make a meaningful comparison;
            # let the request through and rely on other defences.
            return await call_next(request)

        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        source = origin or referer

        if not source:
            # Browsers always send Origin on cross-origin POST/PUT/DELETE
            # (and on same-origin POST since Chrome 76 / Firefox 70). A
            # missing Origin AND missing Referer typically means a
            # non-browser client (curl, server-to-server, etc.) and is
            # acceptable.
            return await call_next(request)

        try:
            source_host = urlparse(source).netloc.lower()
        except ValueError:
            source_host = ""

        if not source_host or source_host != host:
            logger.warning(
                "CSRF block: %s %s host=%s origin=%r referer=%r",
                request.method, request.url.path, host, origin, referer,
            )
            return JSONResponse(
                {"error": "Cross-origin request blocked"}, status_code=403
            )

        return await call_next(request)
