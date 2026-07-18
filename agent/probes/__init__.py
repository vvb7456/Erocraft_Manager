"""Custom user probes (HTTP / TCP)."""

from __future__ import annotations

from ..config import ProbeConfig
from ..schemas import ProbeResult
from . import http as http_probe
from . import tcp as tcp_probe


async def run_probe(cfg: ProbeConfig) -> ProbeResult:
    if cfg.type == "http":
        return await http_probe.run(
            cfg.name, cfg.target, cfg.timeout, cfg.tls_verify, cfg.proxy
        )
    if cfg.type == "tcp":
        return await tcp_probe.run(cfg.name, cfg.target, cfg.timeout)
    raise ValueError(f"unsupported probe type: {cfg.type}")
