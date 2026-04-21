from __future__ import annotations

import time

import httpx

from ..schemas import ProbeResult


async def run(
    name: str,
    target: str,
    timeout: float,
    tls_verify: bool,
    proxy: str | None = None,
) -> ProbeResult:
    """HTTP health probe.

    Treats 2xx/3xx as healthy and 4xx/5xx as failed, matching httpx's
    ``raise_for_status`` convention. Previously any ``< 500`` was counted as
    success, which masked genuine failures — e.g. Clash's HTTP proxy port
    returns 400 to a direct GET, and that must NOT be reported as healthy
    (see Phase-1 CR §1.6). Users who need to cover "proxy port is listening"
    should switch to a TCP probe on the same port.

    :param proxy: Optional outbound proxy URL. When supplied, the request is
        routed through it, so ``latency_ms`` reflects the full end-to-end
        path (client → proxy → target) — useful for validating that a Clash /
        SOCKS proxy can actually forward traffic. Supports ``http://`` and
        (with ``httpx[socks]``) ``socks5://`` schemes.
    """
    start = time.monotonic()
    try:
        client_kwargs: dict = {"verify": tls_verify, "timeout": timeout}
        if proxy:
            client_kwargs["proxy"] = proxy
        async with httpx.AsyncClient(**client_kwargs) as client:
            r = await client.get(target)
            latency = round((time.monotonic() - start) * 1000, 1)
            ok = r.status_code < 400
            return ProbeResult(
                name=name,
                ok=ok,
                latency_ms=latency,
                error_msg=None if ok else f"http {r.status_code}",
            )
    except Exception as e:
        return ProbeResult(name=name, ok=False, error_msg=str(e)[:200])
