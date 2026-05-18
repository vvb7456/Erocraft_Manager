"""cloudflared install / config / lifecycle helpers.

The agent runs as root via systemd (per ``agent/erocraft-agent.service``)
which gives us enough privileges to:

* drop files into ``/etc/cloudflared/``
* write a systemd unit at ``/etc/systemd/system/cloudflared.service``
* invoke ``systemctl daemon-reload / enable / start / stop / restart``

The cloudflared binary itself is **not** auto-downloaded — the operator
must apt-install it (or drop the .deb) before calling
``cloudflared.setup``. We only verify presence and report the version.

We run cloudflared in **remote-managed** mode: ingress lives on Cloudflare
and is push-delivered to the client via long-poll (typically <1s, no restart,
no connection drops). The local ``config.yml`` only contains tunnel id +
credentials path + protocol. See
``docs/CF_REMOTE_MANAGED_TUNNEL_REFACTOR.md``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

from ..utils.atomic import atomic_write_text

log = logging.getLogger("agent.cloudflared_service")

CLOUDFLARED_BIN = "/usr/bin/cloudflared"
CONFIG_DIR = Path("/etc/cloudflared")
CONFIG_PATH = CONFIG_DIR / "config.yml"
SYSTEMD_UNIT_PATH = Path("/etc/systemd/system/cloudflared.service")
SERVICE_NAME = "cloudflared"

SYSTEMD_UNIT_TEMPLATE = """\
[Unit]
Description=cloudflared (managed by erocraft-agent)
After=network-online.target
Wants=network-online.target

[Service]
# 0 = no timeout. cloudflared registers 4 edge connections on startup
# which can occasionally take >90s on slow links — disabling the timeout
# avoids spurious systemd-induced restart loops.
TimeoutStartSec=0
Type=notify
ExecStart=/usr/bin/cloudflared --no-autoupdate --config /etc/cloudflared/config.yml tunnel run
# No ExecReload: cloudflared 2026.x exits on SIGHUP. Ingress changes are
# delivered remotely via Cloudflare's API — no reload signal is needed.
Restart=on-failure
RestartSec=5
User=root
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
"""

#: Hard upper bound for the base64-encoded credentials blob; the real one
#: is ~250 bytes, so 4 KiB is generous yet bounded.
_MAX_CREDENTIALS_B64 = 4096


# ---------------------------------------------------------------------------
# subprocess helper (mirrors wings_service._run for consistency)
# ---------------------------------------------------------------------------


async def _run(cmd: list[str], timeout: float = 30.0) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        return 127, "", f"executable not found: {exc}"
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "", f"timeout after {timeout}s"
    return (
        proc.returncode or 0,
        out.decode("utf-8", "replace"),
        err.decode("utf-8", "replace"),
    )


# ---------------------------------------------------------------------------
# install / version
# ---------------------------------------------------------------------------


async def detect_version() -> str | None:
    """Return cloudflared version string (e.g. ``"2026.3.0"``) or None."""
    if not Path(CLOUDFLARED_BIN).exists():
        return None
    rc, out, err = await _run([CLOUDFLARED_BIN, "--version"], timeout=5.0)
    if rc != 0:
        return None
    # Output looks like "cloudflared version 2026.3.0 (built ...)"
    m = re.search(r"version\s+(\S+)", out)
    return m.group(1) if m else out.strip()[:64]


async def setup(*, force: bool = False) -> dict[str, Any]:
    """Verify cloudflared is present and our systemd unit is in place.

    Does **not** install the binary itself. Returns the version + whether
    the unit file was (re)written.

    Renamed from ``install`` (B5) to make it clear that this command is
    the agent-side preparation step (binary check + unit file), not a
    binary installer.
    """
    version = await detect_version()
    if version is None:
        raise RuntimeError(
            "cloudflared binary not found; install via "
            "`apt-get install -y cloudflared` (or download the .deb from "
            "https://pkg.cloudflare.com/) before running this command"
        )

    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o755)

    desired_unit = SYSTEMD_UNIT_TEMPLATE
    unit_changed = False
    current_unit = SYSTEMD_UNIT_PATH.read_text() if SYSTEMD_UNIT_PATH.exists() else ""
    if force or current_unit != desired_unit:
        SYSTEMD_UNIT_PATH.write_text(desired_unit)
        os.chmod(SYSTEMD_UNIT_PATH, 0o644)
        unit_changed = True
        rc, _, err = await _run(["systemctl", "daemon-reload"])
        if rc != 0:
            raise RuntimeError(f"systemctl daemon-reload failed: {err.strip()}")

    return {"version": version, "unit_written": unit_changed}


# ---------------------------------------------------------------------------
# write_config_minimal
# ---------------------------------------------------------------------------


async def write_config_minimal(
    *,
    tunnel_id: str,
    credentials_b64: str,
    protocol: str = "http2",
) -> dict[str, Any]:
    """Write credentials JSON + minimal config.yml (no ingress).

    Ingress lives on Cloudflare in remote-managed mode; cloudflared fetches
    it on startup and receives push updates thereafter. This function is
    idempotent at the byte level — returns ``{written: False}`` if both
    files already match the desired content.
    """
    if not tunnel_id or not re.fullmatch(r"[0-9a-f-]{36}", tunnel_id):
        raise ValueError(f"invalid tunnel_id: {tunnel_id!r}")
    if len(credentials_b64) > _MAX_CREDENTIALS_B64:
        raise ValueError(
            f"credentials_b64 too large ({len(credentials_b64)} > {_MAX_CREDENTIALS_B64})"
        )

    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o755)

    # Decode + write credentials JSON
    try:
        creds_json = base64.b64decode(credentials_b64).decode("utf-8")
        json.loads(creds_json)  # validate
    except Exception as exc:
        raise ValueError(f"invalid credentials_b64: {exc}") from exc
    creds_path = CONFIG_DIR / f"{tunnel_id}.json"

    config_doc: dict[str, Any] = {
        "tunnel": tunnel_id,
        "credentials-file": str(creds_path),
        "protocol": protocol,
        "no-autoupdate": True,
    }
    yaml_text = yaml.safe_dump(
        config_doc, sort_keys=False, allow_unicode=False, default_flow_style=False,
    )

    creds_changed = (
        not creds_path.exists() or creds_path.read_text() != creds_json
    )
    config_changed = (
        not CONFIG_PATH.exists() or CONFIG_PATH.read_text() != yaml_text
    )
    if not creds_changed and not config_changed:
        return {"written": False}

    if creds_changed:
        atomic_write_text(creds_path, creds_json, mode=0o600)
    if config_changed:
        atomic_write_text(CONFIG_PATH, yaml_text, mode=0o600)
    return {
        "written": True,
        "creds_changed": creds_changed,
        "config_changed": config_changed,
    }


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------


async def restart_service(timeout: float = 30.0) -> dict[str, Any]:
    rc, out, err = await _run(
        ["systemctl", "restart", SERVICE_NAME], timeout=timeout,
    )
    if rc != 0:
        raise RuntimeError(
            f"systemctl restart {SERVICE_NAME} rc={rc}: {err.strip() or out.strip()}"
        )
    return {"rc": rc, "stdout": out.strip(), "stderr": err.strip(), "method": "restart"}


async def enable_and_start(timeout: float = 30.0) -> dict[str, Any]:
    rc, out, err = await _run(
        ["systemctl", "enable", "--now", SERVICE_NAME], timeout=timeout,
    )
    if rc != 0:
        raise RuntimeError(
            f"systemctl enable --now {SERVICE_NAME} rc={rc}: {err.strip() or out.strip()}"
        )
    return {"rc": rc, "stdout": out.strip(), "stderr": err.strip()}


async def status() -> dict[str, Any]:
    """Return current cloudflared install + service status."""
    version = await detect_version()
    installed = version is not None

    active = False
    sub_state = "unknown"
    if SYSTEMD_UNIT_PATH.exists():
        rc, out, _ = await _run(
            ["systemctl", "show", SERVICE_NAME, "-p", "ActiveState,SubState"],
            timeout=5.0,
        )
        if rc == 0:
            for line in out.splitlines():
                if "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip()
                if k == "ActiveState":
                    active = v == "active"
                elif k == "SubState":
                    sub_state = v

    config_present = CONFIG_PATH.exists()

    return {
        "installed": installed,
        "version": version,
        "active": active,
        "sub_state": sub_state,
        "unit_present": SYSTEMD_UNIT_PATH.exists(),
        "config_present": config_present,
    }


async def uninstall(*, remove_config: bool = True) -> dict[str, Any]:
    """Stop + disable cloudflared and (optionally) remove config files.

    Does not uninstall the binary package. Safe to call when nothing is
    installed (returns no-op).
    """
    stopped = False
    if SYSTEMD_UNIT_PATH.exists():
        await _run(["systemctl", "disable", "--now", SERVICE_NAME], timeout=15.0)
        stopped = True
        try:
            SYSTEMD_UNIT_PATH.unlink()
        except FileNotFoundError:
            pass
        await _run(["systemctl", "daemon-reload"], timeout=10.0)

    removed = []
    if remove_config and CONFIG_DIR.exists():
        for p in CONFIG_DIR.iterdir():
            if p.is_file() and p.suffix in (".json", ".yml"):
                try:
                    p.unlink()
                    removed.append(p.name)
                except OSError as exc:
                    log.warning("failed to unlink %s: %s", p, exc)
    return {"stopped": stopped, "removed_files": removed}
