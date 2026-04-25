"""Command handlers.

Phase 1: ping.
PR-A:    wings.restart, wings.status (delegate to collectors.wings_service).

Each handler receives a dict of params and returns a JSON-serializable value
(string, dict, list, etc.). Errors should raise; the dispatcher in
``commands/__init__.py`` will catch and surface them as ``ok=false``.
"""

from __future__ import annotations

from typing import Any

from ..collectors import certificates, wings_service


# Module-level config holder. ``set_config`` is called from
# ``http_app.create_app`` so handlers can read ``cfg.wings.service_name``
# without each command having to plumb config through the dispatcher.
_cfg: Any = None


def set_config(cfg: Any) -> None:
    global _cfg
    _cfg = cfg


def _service_name() -> str:
    if _cfg is None:
        raise RuntimeError("agent config not initialized")
    return _cfg.wings.service_name


async def ping(params: dict) -> str:
    return "pong"


async def wings_restart(params: dict) -> dict:
    """Restart the wings systemd unit. Idempotent from the caller's view."""
    timeout = float(params.get("timeout", 30.0))
    result = await wings_service.restart(_service_name(), timeout=timeout)
    if result["rc"] != 0:
        # Propagate as exception so the dispatcher marks ok=false but still
        # returns the captured stderr for diagnostics.
        raise RuntimeError(
            f"systemctl restart {result['service_name']} rc={result['rc']}: "
            f"{result['stderr'] or result['stdout']}"
        )
    return result


async def wings_status(params: dict) -> dict:
    """Return the current systemd state of the wings unit."""
    s = await wings_service.status(_service_name())
    return s.model_dump(mode="json")


async def cert_install(params: dict) -> dict:
    """Install a certificate/key pair into the paths configured by wings."""
    if _cfg is None:
        raise RuntimeError("agent config not initialized")
    return await certificates.install(
        config_path=_cfg.wings.config_path,
        service_name=_cfg.wings.service_name,
        targets=_cfg.cert_install_targets,
        target_name=str(params.get("target_name") or ""),
        cert_id=params.get("cert_id"),
        fullchain_pem=str(params.get("fullchain_pem") or ""),
        privkey_pem=str(params.get("privkey_pem") or ""),
        timeout=float(params.get("timeout", 30.0)),
    )
