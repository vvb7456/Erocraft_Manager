"""Command handlers.

Each handler receives a dict of params and returns a JSON-serializable value
(string, dict, list, etc.). Errors should raise; the dispatcher in
``commands/__init__.py`` will catch and surface them as ``ok=false``.
"""

from __future__ import annotations

from typing import Any

from ..collectors import certificates, cloudflared_service, wings_service
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
        raise RuntimeError(
            f"this command is only available on wings_node agents "
            f"(current role: {_cfg.agent.role!r})"
        )
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


# ---------------------------------------------------------------------------
# Cloudflare Tunnel (cloudflared) handlers
#
# These run on wings_node hosts only — they share the same systemd /
# subprocess privilege model as wings.* handlers. See agent's
# ``collectors/cloudflared_service.py`` for the actual file/systemd ops
# and ``docs/CLOUDFLARE_TUNNEL_DESIGN.md`` §4 for the protocol.
# ---------------------------------------------------------------------------


async def cloudflared_setup(params: dict) -> dict:
    """Verify cloudflared binary + (re)write our systemd unit.

    params: ``{"force": bool}`` — if true, rewrites unit even when
    already present.
    """
    _wings_cfg()  # gate to wings_node role
    return await cloudflared_service.setup(force=bool(params.get("force", False)))


async def cloudflared_write_config_minimal(params: dict) -> dict:
    """Write credentials JSON + minimal config.yml (no ingress).

    Required params: ``tunnel_id``, ``credentials_b64``. Optional:
    ``protocol`` (default ``"http2"``). Ingress is managed remotely on
    Cloudflare; cloudflared fetches it on startup and receives push
    updates thereafter.
    """
    _wings_cfg()
    return await cloudflared_service.write_config_minimal(
        tunnel_id=str(params["tunnel_id"]),
        credentials_b64=str(params["credentials_b64"]),
        protocol=str(params.get("protocol", "http2")),
    )


async def cloudflared_restart(params: dict) -> dict:
    """``systemctl restart cloudflared``."""
    _wings_cfg()
    return await cloudflared_service.restart_service(
        timeout=float(params.get("timeout", 30.0)),
    )


async def cloudflared_enable(params: dict) -> dict:
    """``systemctl enable --now cloudflared`` — used after first install."""
    _wings_cfg()
    return await cloudflared_service.enable_and_start(
        timeout=float(params.get("timeout", 30.0)),
    )


async def cloudflared_status(params: dict) -> dict:
    """Return current cloudflared install + service status."""
    _wings_cfg()
    return await cloudflared_service.status()


async def cloudflared_uninstall(params: dict) -> dict:
    """Stop + disable + (optionally) remove config files."""
    _wings_cfg()
    return await cloudflared_service.uninstall(
        remove_config=bool(params.get("remove_config", True)),
    )
