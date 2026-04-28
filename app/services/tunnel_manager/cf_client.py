"""Cloudflare API client.

Thin async httpx wrapper for the subset of Cloudflare API operations we need:

* token verification (``GET /user/tokens/verify``)
* zone listing (``GET /zones``)
* tunnel CRUD (``/accounts/{aid}/cfd_tunnel``)
* DNS record CRUD (``/zones/{zid}/dns_records``)

All methods take ``account_id`` + ``api_token`` (decrypted by the caller) and
return parsed CF response objects. Failures map to the typed exceptions in
:mod:`.exceptions` for predictable HTTP translation.

Per ``docs/CLOUDFLARE_TUNNEL_DESIGN.md`` §3.3, we cap concurrency and retry
on 429 with exponential backoff.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import secrets
from typing import Any

import httpx

from .exceptions import (
    CloudflareAPIError,
    CloudflareAuthError,
    CloudflareNotFound,
    CloudflareRateLimited,
)
from .schemas import CFDNSRecord, CFTunnel, CFZone

logger = logging.getLogger(__name__)

CF_BASE = "https://api.cloudflare.com/client/v4"

#: Per-account concurrency cap for outbound CF requests. 4 is well below
#: CF's published 1200 req / 5 min global limit and matches their guidance
#: for batch use cases.
_CONCURRENCY = 4

#: Retry schedule for 429 responses (seconds).
_RETRY_BACKOFF = (1.0, 2.0, 5.0)


class CloudflareClient:
    """Async CF API client bound to one account_id + token pair.

    Construct fresh per request; httpx clients are cheap and we don't share
    them across DB requests anyway. Each instance maintains a semaphore to
    cap concurrency to :data:`_CONCURRENCY` requests in flight.
    """

    def __init__(self, account_id: str, api_token: str, *, timeout: float = 15.0):
        self.account_id = account_id
        self._token = api_token
        self._timeout = timeout
        self._sem = asyncio.Semaphore(_CONCURRENCY)

    # ------------------------------------------------------------------
    # Low-level
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        url = f"{CF_BASE}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

        async with self._sem:
            for attempt, delay in enumerate((0.0,) + _RETRY_BACKOFF):
                if delay:
                    await asyncio.sleep(delay)
                async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as c:
                    try:
                        resp = await c.request(
                            method, url, headers=headers, json=json, params=params,
                        )
                    except httpx.HTTPError as exc:
                        raise CloudflareAPIError(f"network error: {exc}") from exc
                # not rate-limited → process and return
                if resp.status_code != 429:
                    break
                # last attempt? fall through to error handling
                if attempt >= len(_RETRY_BACKOFF):
                    raise CloudflareRateLimited(
                        "Cloudflare API rate limit exceeded after retries",
                        status_code=429,
                    )
                logger.warning(
                    "cf api 429 on %s %s, retrying in %.1fs", method, path, _RETRY_BACKOFF[attempt],
                )

        # Parse body
        try:
            body = resp.json()
        except Exception:
            body = {}

        if 200 <= resp.status_code < 300 and body.get("success") is True:
            return body

        # Error path
        cf_errors = body.get("errors") if isinstance(body, dict) else None
        msg = self._extract_error_msg(body, resp)
        # Log full CF error body so operators can diagnose 4xx without enabling
        # request body logging globally. Token / secret are not present in
        # response bodies so this is safe.
        logger.warning(
            "cf api error %s %s -> HTTP %d: %s | errors=%s",
            method, path, resp.status_code, msg, cf_errors,
        )
        if resp.status_code in (401, 403):
            raise CloudflareAuthError(msg, status_code=resp.status_code, cf_errors=cf_errors)
        if resp.status_code == 404:
            raise CloudflareNotFound(msg, status_code=resp.status_code, cf_errors=cf_errors)
        raise CloudflareAPIError(msg, status_code=resp.status_code, cf_errors=cf_errors)

    @staticmethod
    def _extract_error_msg(body: Any, resp: httpx.Response) -> str:
        if isinstance(body, dict):
            errs = body.get("errors") or []
            if errs and isinstance(errs, list):
                first = errs[0]
                if isinstance(first, dict):
                    msg = first.get("message")
                    code = first.get("code")
                    if msg:
                        return f"CF error {code}: {msg}" if code else msg
        return f"Cloudflare API HTTP {resp.status_code}"

    # ------------------------------------------------------------------
    # Verification & zones
    # ------------------------------------------------------------------

    async def verify_token(self) -> dict[str, Any]:
        """Return the token's verify payload (raises on auth failure)."""
        body = await self._request("GET", "/user/tokens/verify")
        return body.get("result", {})

    async def verify_account_access(self) -> dict[str, Any]:
        """Verify the bound ``account_id`` is actually accessible to this
        token. Catches the case where an admin pastes a valid token but a
        wrong / unrelated account_id.

        We probe ``GET /accounts/{id}/cfd_tunnel?per_page=1`` instead of
        ``GET /accounts/{id}`` because the latter needs ``Account:Read``
        permission that legitimate tunnel-scoped tokens won't have. The
        cfd_tunnel endpoint requires ``Account.Cloudflare Tunnel:Read``
        which the install flow needs anyway, so this is the correct
        permission floor.

        Raises ``CloudflareAuthError`` (mapped to HTTP 400 by the router)
        if the account is not visible to the token.
        """
        try:
            await self._request(
                "GET",
                f"/accounts/{self.account_id}/cfd_tunnel",
                params={"per_page": 1},
            )
        except CloudflareNotFound as exc:
            raise CloudflareAuthError(
                f"account {self.account_id!r} not accessible with this token; "
                "double-check the Account ID matches the token's scope",
                status_code=403,
            ) from exc
        except CloudflareAuthError as exc:
            # CF returns 403 + code 9109 when the account doesn't belong
            # to the token (vs 400 + code 9109 for a malformed account_id,
            # already raised as CloudflareAPIError below).
            raise CloudflareAuthError(
                f"account {self.account_id!r} not accessible with this token "
                f"(Cloudflare said: {exc}); double-check the Account ID matches "
                "the token's scope",
                status_code=403,
            ) from exc
        return {"account_id": self.account_id}

    async def list_zones(self, *, name: str | None = None) -> list[CFZone]:
        """List zones visible to the token. Auto-paginates (CF cap 50/page)."""
        return await self._paginate(
            "/zones", CFZone, extra_params={"name": name} if name else None,
        )

    # ------------------------------------------------------------------
    # Tunnels
    # ------------------------------------------------------------------

    async def list_tunnels(
        self, *, name: str | None = None, is_deleted: bool = False,
    ) -> list[CFTunnel]:
        extra: dict = {"is_deleted": str(is_deleted).lower()}
        if name:
            extra["name"] = name
        return await self._paginate(
            f"/accounts/{self.account_id}/cfd_tunnel", CFTunnel, extra_params=extra,
        )

    async def create_tunnel(self, name: str) -> tuple[CFTunnel, str]:
        """Create a remote-managed tunnel, returning (tunnel, secret_b64).

        We use ``config_src="cloudflare"`` so ingress lives on CF servers and
        is push-delivered to cloudflared via long-poll. See
        ``docs/CF_REMOTE_MANAGED_TUNNEL_REFACTOR.md``.
        """
        secret_b64 = self._generate_tunnel_secret()
        body = await self._request(
            "POST",
            f"/accounts/{self.account_id}/cfd_tunnel",
            json={
                "name": name,
                "tunnel_secret": secret_b64,
                "config_src": "cloudflare",
            },
        )
        return CFTunnel.model_validate(body["result"]), secret_b64

    async def delete_tunnel(self, tunnel_id: str) -> None:
        """Delete a tunnel. 404 (CloudflareNotFound) is **not** raised — it
        means the tunnel was already gone, which is success from our POV."""
        try:
            await self._request(
                "DELETE",
                f"/accounts/{self.account_id}/cfd_tunnel/{tunnel_id}",
            )
        except CloudflareNotFound:
            logger.debug("delete_tunnel: target already gone")

    # ------------------------------------------------------------------
    # Remote-managed tunnel configuration (ingress lives on CF)
    # ------------------------------------------------------------------

    async def get_tunnel_configuration(self, tunnel_id: str) -> dict[str, Any]:
        """GET ``/accounts/{aid}/cfd_tunnel/{tid}/configurations``.

        Returns the unwrapped ``result`` dict, e.g.::

            {
              "tunnel_id": "...",
              "version": 4,
              "config": {"ingress": [...], "warp-routing": {...}},
              "source": "cloudflare" | "local",
            }
        """
        body = await self._request(
            "GET",
            f"/accounts/{self.account_id}/cfd_tunnel/{tunnel_id}/configurations",
        )
        return body["result"]

    async def put_tunnel_configuration(
        self,
        tunnel_id: str,
        *,
        ingress: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """PUT a new ingress list. Auto-flips ``source`` to ``cloudflare``.

        cloudflared receives the new config via long-poll within ~1s and
        applies it in-process — no restart, no connection drops. See
        ``docs/CF_REMOTE_MANAGED_TUNNEL_REFACTOR.md`` §2 for the empirical
        evidence.

        Returns the unwrapped ``result`` (same shape as :meth:`get_tunnel_configuration`).
        """
        body = await self._request(
            "PUT",
            f"/accounts/{self.account_id}/cfd_tunnel/{tunnel_id}/configurations",
            json={"config": {"ingress": ingress}},
        )
        return body["result"]

    @staticmethod
    def _generate_tunnel_secret() -> str:
        """Generate a 32-byte base64-encoded secret as required by CF.

        cloudflared accepts any base64-encoded value of >= 32 bytes; CF will
        reject anything shorter. We use 48 bytes for headroom.
        """
        return base64.b64encode(secrets.token_bytes(48)).decode("ascii")

    # ------------------------------------------------------------------
    # DNS records
    # ------------------------------------------------------------------

    async def list_dns_records(
        self, zone_id: str, *, name: str | None = None,
    ) -> list[CFDNSRecord]:
        return await self._paginate(
            f"/zones/{zone_id}/dns_records",
            CFDNSRecord,
            extra_params={"name": name} if name else None,
        )

    async def create_dns_record(
        self,
        zone_id: str,
        *,
        name: str,
        content: str,
        type: str = "CNAME",
        proxied: bool = True,
        ttl: int = 1,  # 1 = auto when proxied
    ) -> CFDNSRecord:
        body = await self._request(
            "POST",
            f"/zones/{zone_id}/dns_records",
            json={
                "type": type,
                "name": name,
                "content": content,
                "proxied": proxied,
                "ttl": ttl,
            },
        )
        return CFDNSRecord.model_validate(body["result"])

    async def delete_dns_record(self, zone_id: str, record_id: str) -> None:
        try:
            await self._request(
                "DELETE", f"/zones/{zone_id}/dns_records/{record_id}",
            )
        except CloudflareNotFound:
            logger.debug("delete_dns_record: target already gone")

    # ------------------------------------------------------------------
    # Pagination helper
    # ------------------------------------------------------------------

    async def _paginate(
        self,
        path: str,
        model_cls,
        *,
        extra_params: dict | None = None,
        per_page: int = 50,
        max_pages: int = 50,
    ) -> list:
        """GET ``path`` once per page until ``result_info.total_pages`` runs
        out (or ``max_pages`` is reached as a defensive cap).

        ``model_cls`` is a Pydantic model used to validate each item.
        """
        items: list = []
        page = 1
        while page <= max_pages:
            params: dict = {"per_page": per_page, "page": page}
            if extra_params:
                params.update({k: v for k, v in extra_params.items() if v is not None})
            body = await self._request("GET", path, params=params)
            results = body.get("result") or []
            items.extend(model_cls.model_validate(r) for r in results)

            info = body.get("result_info") or {}
            total_pages = info.get("total_pages")
            if not isinstance(total_pages, int) or page >= total_pages:
                break
            page += 1
        return items
