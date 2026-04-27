"""Command handlers.

Each handler receives a dict of params and returns a JSON-serializable value
(string, dict, list, etc.). Errors should raise; the dispatcher in
``commands/__init__.py`` will catch and surface them as ``ok=false``.
"""

from __future__ import annotations

from typing import Any

from ..collectors import certificates, wings_service
from ..config import AgentConfig


# Module-level config holder. ``set_config`` is called from
# ``http_app.create_app`` so handlers can read ``cfg.wings.service_name``
# without each command having to plumb config through the dispatcher.
_cfg: AgentConfig | None = None


def set_config(cfg: AgentConfig) -> None:
    global _cfg
    _cfg = cfg


def _wings_cfg() -> AgentConfig:
    if _cfg is None:
        raise RuntimeError("agent config not initialized")
    if not _cfg.agent.is_wings:
        raise RuntimeError("wings operations are only available on wings_node agents")
    return _cfg


async def ping(params: dict) -> str:
    return "pong"


async def wings_restart(params: dict) -> dict:
    """Restart the wings systemd unit."""
    cfg = _wings_cfg()
    timeout = float(params.get("timeout", 30.0))
    result = await wings_service.restart(cfg.wings.service_name, timeout=timeout)
    if result["rc"] != 0:
        raise RuntimeError(
            f"systemctl restart {result['service_name']} rc={result['rc']}: "
            f"{result['stderr'] or result['stdout']}"
        )
    return result


async def wings_status(params: dict) -> dict:
    """Return the current systemd state of the wings unit."""
    cfg = _wings_cfg()
    s = await wings_service.status(cfg.wings.service_name)
    return s.model_dump(mode="json")


async def cert_install(params: dict) -> dict:
    """Install a certificate/key pair."""
    if _cfg is None:
        raise RuntimeError("agent config not initialized")
    target_name = params.get("target_name")
    cert_id = params.get("cert_id")
    return await certificates.install(
        config_path=_cfg.wings.config_path,
        service_name=_cfg.wings.service_name,
        targets=_cfg.cert_install_targets,
        target_name=str(target_name) if target_name else "",
        cert_id=int(cert_id) if cert_id is not None else None,
        fullchain_pem=str(params.get("fullchain_pem") or ""),
        privkey_pem=str(params.get("privkey_pem") or ""),
        timeout=float(params.get("timeout", 30.0)),
    )
