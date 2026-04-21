from __future__ import annotations

import asyncio
import time

from ..schemas import ProbeResult


async def run(name: str, target: str, timeout: float) -> ProbeResult:
    if ":" not in target:
        return ProbeResult(name=name, ok=False, error_msg=f"invalid tcp target: {target}")
    host, port_str = target.rsplit(":", 1)
    try:
        port = int(port_str)
    except ValueError:
        return ProbeResult(name=name, ok=False, error_msg=f"invalid port: {port_str}")
    start = time.monotonic()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        latency = round((time.monotonic() - start) * 1000, 1)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return ProbeResult(name=name, ok=True, latency_ms=latency)
    except Exception as e:
        return ProbeResult(name=name, ok=False, error_msg=str(e)[:200])
