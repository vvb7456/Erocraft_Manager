"""systemd / journalctl helpers for the wings unit.

Pure stdlib (subprocess + asyncio). Requires the agent process to have
permission to invoke `systemctl` / `journalctl` for the unit named in
`cfg.wings.service_name` (typically `pterodactyl-wings`). On a normal
deployment the agent runs as root via systemd, which is enough.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncIterator

from ..schemas import WingsServiceStatus


log = logging.getLogger("agent.wings_service")


async def _run(cmd: list[str], timeout: float) -> tuple[int, str, str]:
    """Run ``cmd`` and return (returncode, stdout, stderr). Never raises."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        return 127, "", f"executable not found: {e}"
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "", f"timeout after {timeout}s"
    return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


async def restart(service_name: str, timeout: float = 30.0) -> dict:
    """`systemctl restart <unit>`. Returns dict with rc/stdout/stderr."""
    rc, out, err = await _run(["systemctl", "restart", service_name], timeout=timeout)
    log.info("wings restart %s rc=%d", service_name, rc)
    return {"service_name": service_name, "rc": rc, "stdout": out.strip(), "stderr": err.strip()}


def _parse_show(text: str) -> dict[str, str]:
    """Parse `systemctl show -p K=V K=V ...` output into a dict."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def _parse_systemd_ts(value: str) -> datetime | None:
    """Parse systemd's ExecMainStartTimestamp / ActiveEnterTimestamp.

    Format examples:
      "Wed 2024-05-01 12:34:56 UTC"
      "Wed 2024-05-01 20:34:56 CST"
      "" (when not yet started)
    Returns timezone-aware UTC datetime, or None on failure.
    """
    value = value.strip()
    if not value or value in ("0", "n/a"):
        return None
    # Strip leading weekday like "Wed "
    parts = value.split(" ", 1)
    if len(parts) == 2 and len(parts[0]) == 3 and parts[0].isalpha():
        value = parts[1]
    # Now expect "YYYY-MM-DD HH:MM:SS TZ"
    try:
        date_part, time_part, tz_part = value.split(" ")
        dt = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M:%S")
        tz_upper = tz_part.upper()
        if tz_upper in ("UTC", "GMT", "Z"):
            return dt.replace(tzinfo=timezone.utc)
        # Non-UTC timezone abbreviation. systemd prints local-time
        # abbreviations (CST, EST, JST, …) for which Python has no
        # built-in mapping. Treat the timestamp as wall-clock local
        # time and convert to UTC via the system tz database.
        local = dt.astimezone()  # naive → local-aware (Python 3.6+)
        return local.astimezone(timezone.utc)
    except (ValueError, IndexError):
        return None


async def status(service_name: str, timeout: float = 5.0) -> WingsServiceStatus:
    """Query systemd for the unit's current state."""
    # Use comma-separated form for -p so systemctl treats the rest of argv as
    # zero unit names (correct) instead of treating "SubState" / "MainPID" as
    # extra unit-name arguments alongside ``service_name`` (which silently
    # merges results across nonexistent units and reports ActiveState=inactive
    # / MainPID=0).
    props = "ActiveState,SubState,MainPID,ActiveEnterTimestamp,ExecMainStartTimestamp"
    rc, out, err = await _run(
        ["systemctl", "show", service_name, "-p", props],
        timeout=timeout,
    )
    if rc != 0:
        return WingsServiceStatus(
            service_name=service_name,
            error=err.strip() or f"systemctl show rc={rc}",
        )
    fields = _parse_show(out)
    main_pid_raw = fields.get("MainPID", "0")
    try:
        main_pid: int | None = int(main_pid_raw) or None
    except ValueError:
        main_pid = None
    since = (
        _parse_systemd_ts(fields.get("ExecMainStartTimestamp", ""))
        or _parse_systemd_ts(fields.get("ActiveEnterTimestamp", ""))
    )
    return WingsServiceStatus(
        service_name=service_name,
        active_state=fields.get("ActiveState") or None,
        sub_state=fields.get("SubState") or None,
        main_pid=main_pid,
        since=since,
    )


async def stream_logs(service_name: str, lines: int = 100) -> AsyncIterator[bytes]:
    """Yield raw bytes from `journalctl -u <unit> -f -n <lines> --no-pager`.

    Caller is responsible for SSE framing. The subprocess is killed when
    the async generator is closed (i.e. when the HTTP client disconnects).
    """
    proc = await asyncio.create_subprocess_exec(
        "journalctl",
        "-u", service_name,
        "-f",
        "-n", str(lines),
        "--no-pager",
        "--output=short-iso",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                # journalctl exited unexpectedly; surface stderr if any
                err = b""
                if proc.stderr is not None:
                    try:
                        err = await asyncio.wait_for(proc.stderr.read(), timeout=0.5)
                    except asyncio.TimeoutError:
                        pass
                if err:
                    yield b"[journalctl-stderr] " + err
                break
            yield line
    finally:
        if proc.returncode is None:
            proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
