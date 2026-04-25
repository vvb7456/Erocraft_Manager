"""Pure HTTP client for the Erocraft Agent V2.

This module is **transport only**: it knows nothing about the manager
database, the host registry, or how credentials are stored. Callers must
resolve ``(endpoint, token)`` themselves — typically via
:func:`app.services.host_registry.get_credentials` /
:func:`app.services.host_registry.get_credentials_for_node`.

This separation keeps the HTTP retry / SSE / timeout logic in one place
without entangling it with SQLAlchemy sessions or Fernet decryption.

Error model:
  * :class:`AgentClientError` — transport failure or HTTP 4xx/5xx response.
    The message is intentionally terse (no full URL, no body dump) so
    log lines that print ``str(exc)`` cannot leak the agent's private
    ingress. Full diagnostics go to ``logger.debug``.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0


class AgentClientError(Exception):
    """Raised when an agent HTTP call fails (transport or non-2xx)."""


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _request(
    method: str,
    endpoint: str,
    token: str,
    path: str,
    *,
    json: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    url = f"{endpoint}{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(
            timeout=timeout, verify=True, trust_env=False,
        ) as client:
            resp = await client.request(method, url, json=json, headers=headers)
    except httpx.HTTPError as exc:
        logger.debug("agent %s %s transport error: %r", method, url, exc)
        raise AgentClientError(
            f"{method} {path} transport error: {type(exc).__name__}"
        ) from exc
    if resp.status_code >= 400:
        body_hint = resp.text[:80].replace("\n", " ") if resp.text else ""
        logger.debug(
            "agent %s %s -> HTTP %d body=%r",
            method, url, resp.status_code, resp.text[:500],
        )
        raise AgentClientError(
            f"{method} {path} -> HTTP {resp.status_code}"
            + (f": {body_hint}" if body_hint else "")
        )
    return resp.json()


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


async def fetch_metrics(
    endpoint: str, token: str, *, timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    return await _request("GET", endpoint, token, "/v1/metrics", timeout=timeout)


async def fetch_wings_config(
    endpoint: str, token: str, *, timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    return await _request("GET", endpoint, token, "/v1/wings/config", timeout=timeout)


async def fetch_status(
    endpoint: str, token: str, *, timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    return await _request("GET", endpoint, token, "/v1/status", timeout=timeout)


async def get_wings_service(
    endpoint: str, token: str, *, timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """Return systemd state of the wings unit on this node."""
    return await _request("GET", endpoint, token, "/v1/wings/service", timeout=timeout)


async def get_cert_status(
    endpoint: str, token: str, *, timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """Return the certificate status reported by the agent."""
    return await _request("GET", endpoint, token, "/v1/cert/status", timeout=timeout)


# ---------------------------------------------------------------------------
# Command endpoints
# ---------------------------------------------------------------------------


async def ping(endpoint: str, token: str, *, timeout: float = 5.0) -> dict:
    return await _request(
        "POST", endpoint, token, "/v1/commands",
        json={"id": 0, "type": "ping", "params": {}},
        timeout=timeout,
    )


async def restart_wings(
    endpoint: str, token: str, *, timeout: float = 60.0,
) -> dict:
    """Issue the ``wings.restart`` command (subprocess timeout 30s on the agent)."""
    return await _request(
        "POST", endpoint, token, "/v1/commands",
        json={"id": 0, "type": "wings.restart", "params": {"timeout": 30.0}},
        timeout=timeout,
    )


async def install_cert(
    endpoint: str,
    token: str,
    *,
    cert_id: int,
    fullchain_pem: str,
    privkey_pem: str,
    target_name: str = "",
    command_timeout: float = 30.0,
    timeout: float = 90.0,
) -> dict:
    """Issue the ``cert.install`` command to the agent.

    ``command_timeout`` is forwarded to the agent for the local
    ``systemctl restart`` budget. ``timeout`` is the HTTP request budget for
    the full command, including PEM writes, restart, and agent self-check.
    """
    return await _request(
        "POST", endpoint, token, "/v1/commands",
        json={
            "id": 0,
            "type": "cert.install",
            "params": {
                "cert_id": cert_id,
                "target_name": target_name,
                "fullchain_pem": fullchain_pem,
                "privkey_pem": privkey_pem,
                "timeout": command_timeout,
            },
        },
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Unauthenticated reachability
# ---------------------------------------------------------------------------


async def healthz(endpoint: str, *, timeout: float = 3.0) -> bool:
    """Unauthenticated health check used during initial host registration."""
    url = f"{endpoint.rstrip('/')}/healthz"
    try:
        async with httpx.AsyncClient(
            timeout=timeout, verify=True, trust_env=False,
        ) as client:
            resp = await client.get(url)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


async def stream_wings_logs(
    endpoint: str,
    token: str,
    *,
    lines: int = 100,
    connect_timeout: float = 10.0,
) -> AsyncIterator[bytes]:
    """Yield raw SSE bytes from ``/v1/wings/logs/stream``.

    The httpx stream + AsyncClient stay open for the lifetime of this
    generator. Caller iterates until EOF or calls ``aclose()`` to
    terminate the upstream tail. There is no overall request timeout;
    only the connect phase is bounded.
    """
    url = f"{endpoint}/v1/wings/logs/stream?lines={int(lines)}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
    timeout = httpx.Timeout(
        connect_timeout, read=None, write=connect_timeout, pool=connect_timeout,
    )
    client = httpx.AsyncClient(timeout=timeout, verify=True, trust_env=False)
    try:
        async with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode("utf-8", "replace")[:200]
                logger.debug(
                    "agent log stream %s -> HTTP %d body=%r",
                    url, resp.status_code, body,
                )
                raise AgentClientError(
                    f"GET /v1/wings/logs/stream -> HTTP {resp.status_code}"
                    + (f": {body}" if body else "")
                )
            async for chunk in resp.aiter_raw():
                if chunk:
                    yield chunk
    finally:
        await client.aclose()
