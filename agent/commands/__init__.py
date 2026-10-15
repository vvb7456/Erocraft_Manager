"""Dispatch valid RPC requests without converting command failures into HTTP errors."""

from __future__ import annotations

import time
import logging

from ..schemas import CommandRequest, CommandResponse
from ..contracts import CommandFailure, CommandSuccess, ErrorInfo, OperationResult
from ..error_codes import ErrorCode
from . import handlers
from ..command_errors import CommandExecutionError
from ..collectors.certificates import CertificateError


HANDLERS = {
    "ping": handlers.ping,
    "wings.restart": handlers.wings_restart,
    "wings.status": handlers.wings_status,
    "cert.install": handlers.cert_install,
    # Cloudflare Tunnel (remote-managed) — see
    # docs/CF_REMOTE_MANAGED_TUNNEL_REFACTOR.md
    "cloudflared.setup": handlers.cloudflared_setup,
    "cloudflared.write_config_minimal": handlers.cloudflared_write_config_minimal,
    "cloudflared.restart": handlers.cloudflared_restart,
    "cloudflared.enable": handlers.cloudflared_enable,
    "cloudflared.status": handlers.cloudflared_status,
    "cloudflared.uninstall": handlers.cloudflared_uninstall,
}


async def execute(req: CommandRequest) -> CommandResponse:
    start = time.monotonic()
    target = {key: value for key, value in (req.params or {}).items() if key in {"cert_id", "target_name", "tunnel_id"} and isinstance(value, (str, int))}
    action = req.type
    phase = "observation" if action in {"ping", "wings.status", "cloudflared.status"} else "execution"

    def failed(error: ErrorInfo) -> CommandFailure:
        return CommandFailure(
            id=req.id, error=error, duration_ms=int((time.monotonic() - start) * 1000),
            operation=OperationResult(action=action, phase=phase, outcome="failed", target=target, error=error),
        )

    handler = HANDLERS.get(req.type)
    if handler is None:
        return failed(ErrorInfo(code="agent.command_unsupported"))
    try:
        output = await handler(req.params or {})
        return CommandSuccess(
            id=req.id,
            ok=True,
            output=output,
            duration_ms=int((time.monotonic() - start) * 1000),
            operation=OperationResult(action=action, phase=phase, outcome="success", target=target),
        )
    except (ValueError, KeyError) as exc:
        return failed(ErrorInfo(code="agent.command_invalid_params", detail=str(exc)[:500]))
    except (CommandExecutionError, CertificateError, OSError) as exc:
        logging.getLogger(__name__).warning("agent command failed action=%s id=%s: %s", action, req.id, exc)
        codes: dict[str, ErrorCode] = {"wings.restart": "wings.restart_failed", "cert.install": "certificate.deploy_failed"}
        return failed(ErrorInfo(code=codes.get(action, "agent.command_failed"), detail=str(exc)[:500]))
    except Exception as e:
        logging.getLogger(__name__).exception("agent command failed action=%s id=%s", action, req.id)
        return failed(ErrorInfo(code="system.internal_error"))
