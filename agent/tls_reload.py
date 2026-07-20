"""Hot-reload the agent's own TLS listener certificate without a restart.

Background
----------
uvicorn builds a single :class:`ssl.SSLContext` at startup and hands it to the
listening socket. Calling :meth:`ssl.SSLContext.load_cert_chain` again on that
*same* object makes new TLS handshakes use the fresh cert; connections already
negotiated keep the cert they have. A background poller watches the cert file
and reloads on fingerprint change, so a renewed certificate — written locally
by acme.sh or pushed by the Manager via ``cert.install`` — starts serving
within one poll interval.

Why this matters
----------------
Before this, the agent read its TLS cert exactly once at process start. When
the fleet wildcard renewed, nothing restarted the agent, so it kept serving the
old (eventually expired) cert. Once expired, the Manager's ``verify=True``
client could no longer connect, so it could neither push a new cert nor trigger
a restart — a deadlock only breakable by shell access to the node. Hot-reload
removes both the manual-restart requirement and that deadlock.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .collectors.certificates import summarize_cert_file

#: How often to re-check the cert file. The Manager polls agents every ~60s, so
#: a renewed cert served within this window is picked up promptly either way.
DEFAULT_POLL_INTERVAL = 30.0


@dataclass
class TlsReloadState:
    """Live state for the agent listener's certificate.

    ``serving`` mirrors the leaf certificate currently loaded into the
    in-memory SSLContext (what clients actually get), which may briefly differ
    from the on-disk file between a renewal and the next poll.
    """

    context: ssl.SSLContext
    cert_path: str
    key_path: str
    poll_interval: float = DEFAULT_POLL_INTERVAL
    serving: dict[str, Any] | None = None
    last_error: str | None = None
    task: asyncio.Task | None = field(default=None, repr=False)


def record_initial(state: TlsReloadState) -> None:
    """Record what uvicorn already loaded at startup (no reload performed)."""
    state.serving = summarize_cert_file(Path(state.cert_path))


async def watch(state: TlsReloadState, log: logging.Logger) -> None:
    """Poll the cert file; reload the SSLContext when its fingerprint changes."""
    served_fp = (state.serving or {}).get("fingerprint_sha256")
    while True:
        try:
            await asyncio.sleep(state.poll_interval)
            info = summarize_cert_file(Path(state.cert_path))
            fp = (info or {}).get("fingerprint_sha256")
            if not fp or fp == served_fp:
                continue
            try:
                state.context.load_cert_chain(state.cert_path, state.key_path)
            except (ssl.SSLError, OSError, ValueError) as exc:
                # Unreadable file or cert/key mismatch mid-rotation — keep
                # serving the previous cert and retry next tick.
                state.last_error = str(exc)
                log.error("TLS hot-reload failed (%s): %s", state.cert_path, exc)
                continue
            state.serving = info
            state.last_error = None
            served_fp = fp
            log.warning(
                "TLS listener cert hot-reloaded: fp=%s… not_after=%s",
                fp[:16], (info or {}).get("not_after"),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — never let the watcher die
            log.exception("TLS watcher iteration error: %s", exc)


def listener_status(state: TlsReloadState | None) -> dict[str, Any]:
    """Describe the agent's own listener cert for ``/v1/cert/status``.

    Reports both the in-memory (``serving``) and on-disk (``file``) leaf so the
    Manager can detect a stale listener even before a poll picks it up.
    """
    if state is None:
        return {"tls_enabled": False}
    file_info = summarize_cert_file(Path(state.cert_path))
    serving_fp = (state.serving or {}).get("fingerprint_sha256")
    file_fp = (file_info or {}).get("fingerprint_sha256")
    return {
        "tls_enabled": True,
        "hot_reload": state.task is not None and not state.task.done(),
        "cert_path": state.cert_path,
        "serving": state.serving,
        "file": file_info,
        "in_sync": bool(serving_fp and serving_fp == file_fp),
        "last_error": state.last_error,
    }
