"""Local acme.sh discovery and renew helpers.

Manager does not issue certificates itself in the current phase. This module
only inventories the local acme.sh home and runs a tightly-scoped
``acme.sh --renew -d <known-domain> --force`` for certificates that already
exist there.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings

from .pem import CertPemError, parse_material


class AcmeShError(RuntimeError):
    """Raised when local acme.sh state cannot be used."""


@dataclass(frozen=True, slots=True)
class AcmeShCertificate:
    domain: str
    alt_names: list[str]
    is_ecc: bool
    conf_path: str
    cert_dir: str
    source_path: str | None
    source_compatible: bool
    fullchain_path: str | None
    key_path: str | None
    cert_create_time: str | None
    cert_create_time_iso: str | None
    next_renew_time: str | None
    next_renew_time_iso: str | None
    ca: str | None
    webroot: str | None
    reload_cmd_set: bool
    fingerprint_sha256: str | None
    not_before: datetime | None
    not_after: datetime | None
    source_error: str | None


def acme_home() -> Path:
    return Path(get_settings().cert_acme_sh_home)


def acme_binary() -> Path:
    return Path(get_settings().cert_acme_sh_bin)


def _strip_shell_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_conf(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text("utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = _strip_shell_value(value)
    return out


def _split_alt(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _iso_from_epoch(value: str | None) -> str | None:
    if not value or not value.isdigit():
        return None
    try:
        return datetime.fromtimestamp(int(value), UTC).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def _load_pair(fullchain_path: Path | None, key_path: Path | None) -> tuple[str | None, datetime | None, datetime | None, str | None]:
    if fullchain_path is None or key_path is None:
        return None, None, None, "fullchain/key paths are not available"
    try:
        parsed = parse_material(fullchain_path.read_bytes(), key_path.read_bytes())
        return parsed.fingerprint_sha256, parsed.not_before, parsed.not_after, None
    except (OSError, CertPemError) as exc:
        return None, None, None, str(exc)


def _path_or_none(value: str | None) -> Path | None:
    if not value:
        return None
    return Path(value)


def _source_path_for(conf_dir: Path, fullchain_path: Path | None, key_path: Path | None) -> tuple[str | None, bool]:
    if fullchain_path and key_path and fullchain_path.parent == key_path.parent:
        parent = fullchain_path.parent
        compatible = (
            (parent / "fullchain.pem").exists()
            and ((parent / "privkey.pem").exists() or (parent / "key.pem").exists())
        ) or (
            (parent / "fullchain.cer").exists()
            and any(parent.glob("*.key"))
        )
        return str(parent), compatible
    native_fullchain = conf_dir / "fullchain.cer"
    native_keys = list(conf_dir.glob("*.key"))
    if native_fullchain.exists() and native_keys:
        return str(conf_dir), True
    return None, False


def discover_certificates() -> list[AcmeShCertificate]:
    home = acme_home()
    if not home.exists():
        return []

    certs: list[AcmeShCertificate] = []
    for conf_path in sorted(home.glob("*/*.conf")):
        if conf_path.name.endswith(".csr.conf"):
            continue
        data = _parse_conf(conf_path)
        domain = data.get("Le_Domain") or conf_path.stem
        if not domain:
            continue
        conf_dir = conf_path.parent
        is_ecc = conf_dir.name.endswith("_ecc")
        fullchain_path = _path_or_none(data.get("Le_RealFullChainPath"))
        key_path = _path_or_none(data.get("Le_RealKeyPath"))
        if fullchain_path is None or key_path is None:
            fullchain_path = conf_dir / "fullchain.cer"
            key_path = conf_dir / f"{domain}.key"
        source_path, compatible = _source_path_for(conf_dir, fullchain_path, key_path)
        fingerprint, not_before, not_after, source_error = _load_pair(fullchain_path, key_path)
        certs.append(
            AcmeShCertificate(
                domain=domain,
                alt_names=_split_alt(data.get("Le_Alt")),
                is_ecc=is_ecc,
                conf_path=str(conf_path),
                cert_dir=str(conf_dir),
                source_path=source_path,
                source_compatible=compatible,
                fullchain_path=str(fullchain_path) if fullchain_path else None,
                key_path=str(key_path) if key_path else None,
                cert_create_time=data.get("Le_CertCreateTime"),
                cert_create_time_iso=data.get("Le_CertCreateTimeStr") or _iso_from_epoch(data.get("Le_CertCreateTime")),
                next_renew_time=data.get("Le_NextRenewTime"),
                next_renew_time_iso=data.get("Le_NextRenewTimeStr") or _iso_from_epoch(data.get("Le_NextRenewTime")),
                ca=data.get("Le_API"),
                webroot=data.get("Le_Webroot"),
                reload_cmd_set=bool(data.get("Le_ReloadCmd")),
                fingerprint_sha256=fingerprint,
                not_before=not_before,
                not_after=not_after,
                source_error=source_error,
            )
        )
    return certs


def find_certificate(domain: str, is_ecc: bool | None = None) -> AcmeShCertificate | None:
    for cert in discover_certificates():
        if cert.domain != domain:
            continue
        if is_ecc is not None and cert.is_ecc != is_ecc:
            continue
        return cert
    return None


def status() -> dict[str, Any]:
    home = acme_home()
    binary = acme_binary()
    return {
        "home": str(home),
        "binary": str(binary),
        "home_exists": home.exists(),
        "binary_exists": binary.exists(),
        "binary_executable": binary.exists() and binary.is_file() and os.access(binary, os.X_OK),
        "certificate_count": len(discover_certificates()),
    }


_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [^-]+-----.*?-----END [^-]+-----",
    re.DOTALL,
)
_SENSITIVE_LINE_RE = re.compile(
    r"(token|secret|password|passwd|key=|_key|cf_|dnspod|ali_)",
    re.IGNORECASE,
)


def _sanitize_output(text: str, *, max_lines: int = 120, max_chars: int = 12000) -> str:
    text = _PEM_BLOCK_RE.sub("[pem block omitted]", text)
    safe_lines: list[str] = []
    for line in text.splitlines():
        safe_lines.append("[sensitive line omitted]" if _SENSITIVE_LINE_RE.search(line) else line)
    safe = "\n".join(safe_lines[-max_lines:])
    if len(safe) > max_chars:
        safe = safe[-max_chars:]
    return safe


async def renew_force(domain: str, *, is_ecc: bool, timeout: float = 420.0) -> dict[str, Any]:
    cert = find_certificate(domain, is_ecc)
    if cert is None:
        raise AcmeShError(f"acme.sh certificate not found: {domain}")
    binary = acme_binary()
    if not binary.exists() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise AcmeShError(f"acme.sh binary is not executable: {binary}")

    cmd = [str(binary), "--renew", "-d", cert.domain, "--force"]
    if cert.is_ecc:
        cmd.append("--ecc")
    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(acme_home()),
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.communicate()
        raise AcmeShError(f"acme.sh renew timed out after {int(timeout)}s") from exc

    output = _sanitize_output(stdout.decode("utf-8", "replace"))
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "duration_ms": int((time.monotonic() - start) * 1000),
        "domain": cert.domain,
        "is_ecc": cert.is_ecc,
        "output": output,
        "command": "acme.sh --renew -d <domain> --force" + (" --ecc" if cert.is_ecc else ""),
    }
