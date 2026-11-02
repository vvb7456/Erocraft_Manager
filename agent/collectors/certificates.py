"""Certificate status and install helpers for wings TLS files."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from ..config import CertInstallTargetFile
from ..utils.atomic import atomic_write_bytes
from . import wings, wings_config, wings_service


class CertificateError(Exception):
    """Raised when certificate status or installation cannot proceed."""


def _utc_datetime(cert: x509.Certificate, attr: str) -> datetime:
    """Return a timezone-aware UTC datetime from a certificate attribute.

    cryptography >= 42 provides *_utc properties; fall back to naive UTC
    properties on older releases.
    """
    value = getattr(cert, f"{attr}_utc", None)
    return value if value is not None else getattr(cert, attr)


def _load_cert(pem: bytes) -> x509.Certificate:
    try:
        return x509.load_pem_x509_certificate(pem)
    except ValueError as exc:
        raise CertificateError("invalid fullchain PEM: no leaf certificate") from exc


def _load_key(pem: bytes) -> PrivateKeyTypes:
    try:
        key = load_pem_private_key(pem, password=None)
    except (TypeError, ValueError) as exc:
        raise CertificateError("invalid private key PEM") from exc
    return key


def _public_key_bytes(key: Any) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _cert_public_key_bytes(cert: x509.Certificate) -> bytes:
    return cert.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _fingerprint(cert: x509.Certificate) -> str:
    return cert.fingerprint(hashes.SHA256()).hex()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _cert_summary(cert_path: Path) -> dict[str, Any]:
    pem = cert_path.read_bytes()
    cert = _load_cert(pem)
    return _cert_summary_from_cert(cert, file_sha256=hashlib.sha256(pem).hexdigest())


def _cert_summary_from_cert(
    cert: x509.Certificate,
    *,
    file_sha256: str | None = None,
) -> dict[str, Any]:
    san: list[str] = []
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        san = list(ext.value.get_values_for_type(x509.DNSName))
    except x509.ExtensionNotFound:
        san = []
    return {
        "fingerprint_sha256": _fingerprint(cert),
        "file_sha256": file_sha256,
        "subject": cert.subject.rfc4514_string(),
        "san": san,
        "not_before": _utc_datetime(cert, "not_valid_before"),
        "not_after": _utc_datetime(cert, "not_valid_after"),
    }


def summarize_cert_file(cert_path: Path) -> dict[str, Any] | None:
    """Return a JSON-friendly leaf summary for a PEM file, or ``None``.

    Unlike :func:`_cert_summary` (which returns ``datetime`` objects for
    internal comparisons), datetimes here are ISO strings so the result can be
    dropped straight into an HTTP response. Returns ``None`` when the file is
    missing or unparseable — callers treat that as "nothing to compare".
    """
    try:
        if not cert_path.exists():
            return None
        summary = _cert_summary(cert_path)
    except (CertificateError, OSError):
        return None
    not_before = summary.get("not_before")
    not_after = summary.get("not_after")
    return {
        "fingerprint_sha256": summary.get("fingerprint_sha256"),
        "subject": summary.get("subject"),
        "san": summary.get("san"),
        "not_before": not_before.isoformat() if not_before else None,
        "not_after": not_after.isoformat() if not_after else None,
    }


def status(config_path: str) -> dict[str, Any]:
    """Return wings TLS paths and current leaf certificate metadata."""
    paths = wings_config.read_ssl_paths(config_path)
    cert_path_raw = paths.get("cert")
    current_cert: dict[str, Any] | None = None
    error: str | None = None
    if cert_path_raw:
        cert_path = Path(cert_path_raw)
        if cert_path.exists():
            try:
                current_cert = _cert_summary(cert_path)
            except CertificateError as exc:
                error = str(exc)
            except OSError as exc:
                error = f"failed to read cert: {exc}"
        else:
            error = f"cert file not found: {cert_path}"
    return {
        "wings_yaml_paths": paths,
        "current_cert": current_cert,
        "error": error,
    }


async def _target_status_one(target: CertInstallTargetFile) -> dict[str, Any]:
    cert_path = Path(target.cert_path)
    current_cert: dict[str, Any] | None = None
    error: str | None = None
    if cert_path.exists():
        try:
            current_cert = _cert_summary(cert_path)
        except CertificateError as exc:
            error = str(exc)
        except OSError as exc:
            error = f"failed to read cert: {exc}"
    else:
        error = f"cert file not found: {cert_path}"
    return {
        "name": target.name,
        "type": "file",
        "paths": {"cert": target.cert_path, "key": target.key_path},
        "current_cert": current_cert,
        "error": error,
    }


async def _target_status_async(targets: list[Any]) -> list[dict[str, Any]]:
    return [await _target_status_one(target) for target in targets]


async def status_with_targets(config_path: str, targets: list[Any]) -> dict[str, Any]:
    try:
        payload = status(config_path)
    except wings_config.WingsConfigError as exc:
        payload = {
            "wings_yaml_paths": {"cert": None, "key": None},
            "current_cert": None,
            "error": str(exc),
        }
    payload["targets"] = await _target_status_async(targets)
    return payload


def _validate_install_payload(fullchain_pem: str, privkey_pem: str) -> tuple[bytes, bytes, x509.Certificate]:
    fullchain = fullchain_pem.encode("utf-8")
    privkey = privkey_pem.encode("utf-8")
    cert = _load_cert(fullchain)
    key = _load_key(privkey)
    if _cert_public_key_bytes(cert) != _public_key_bytes(key):
        raise CertificateError("certificate and private key do not match")
    return fullchain, privkey, cert


def _backup(path: Path) -> str | None:
    if not path.exists():
        return None
    backup_path = path.with_name(path.name + ".bak")
    shutil.copy2(path, backup_path)
    return str(backup_path)


def _atomic_write(path: Path, data: bytes, *, mode: int) -> dict[str, Any]:
    backup_path = _backup(path)
    atomic_write_bytes(path, data, mode=mode)
    return {
        "path": str(path),
        "backup": backup_path,
        "sha256": _sha256_file(path),
        "mode": oct(stat.S_IMODE(path.stat().st_mode)),
    }


async def _probe_wings_until_ready(config_path: str, *, timeout: float = 10.0) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout
    last: dict[str, Any] | None = None
    token = wings_config.read_daemon_token(config_path)
    base_url = wings_config.read_local_wings_url(config_path)
    while asyncio.get_running_loop().time() < deadline:
        result = await wings.probe_wings(base_url, token, timeout=5.0)
        last = result.model_dump(mode="json")
        if result.ok:
            return last
        await asyncio.sleep(1.0)
    return last or {"ok": False, "error": "wings self-check timed out"}


async def _run_reload_cmd(cmd: str, timeout: float) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        return {"rc": 124, "stdout": "", "stderr": f"timeout after {timeout}s"}
    return {
        "rc": proc.returncode or 0,
        "stdout": out.decode("utf-8", "replace").strip(),
        "stderr": err.decode("utf-8", "replace").strip(),
    }


async def _install_named_target(
    *,
    targets: list[Any],
    target_name: str,
    cert_id: int | None,
    fullchain_pem: str,
    privkey_pem: str,
    timeout: float,
) -> dict[str, Any]:
    target = next((item for item in targets if item.name == target_name), None)
    if target is None:
        raise CertificateError(f"unknown certificate target: {target_name}")

    fullchain, privkey, cert = _validate_install_payload(fullchain_pem, privkey_pem)
    written = {
        "cert": _atomic_write(Path(target.cert_path), fullchain, mode=0o644),
        "key": _atomic_write(Path(target.key_path), privkey, mode=0o600),
    }
    reload_result = None
    if target.reload_cmd:
        reload_result = await _run_reload_cmd(target.reload_cmd, timeout=timeout)
        if reload_result.get("rc") != 0:
            raise CertificateError(
                f"reload command failed rc={reload_result.get('rc')}: "
                f"{reload_result.get('stderr') or reload_result.get('stdout') or ''}"
            )
    return {
        "cert_id": cert_id,
        "target_name": target_name,
        "fingerprint_sha256": _fingerprint(cert),
        "not_before": _utc_datetime(cert, "not_valid_before"),
        "not_after": _utc_datetime(cert, "not_valid_after"),
        "written": written,
        "reload_result": reload_result,
    }


async def install(
    *,
    config_path: str,
    service_name: str,
    targets: list[Any] | None = None,
    target_name: str = "",
    cert_id: int | None,
    fullchain_pem: str,
    privkey_pem: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Install PEM files to wings-configured paths and restart wings."""
    if target_name:
        return await _install_named_target(
            targets=targets or [],
            target_name=target_name,
            cert_id=cert_id,
            fullchain_pem=fullchain_pem,
            privkey_pem=privkey_pem,
            timeout=timeout,
        )

    fullchain, privkey, cert = _validate_install_payload(fullchain_pem, privkey_pem)
    paths = wings_config.read_ssl_paths(config_path)
    cert_path_raw = paths.get("cert")
    key_path_raw = paths.get("key")
    if not cert_path_raw or not key_path_raw:
        raise CertificateError("wings yaml missing api.ssl.cert/key paths")

    cert_path = Path(cert_path_raw)
    key_path = Path(key_path_raw)
    written = {
        "cert": _atomic_write(cert_path, fullchain, mode=0o644),
        "key": _atomic_write(key_path, privkey, mode=0o600),
    }

    restart_result = await wings_service.restart(service_name, timeout=timeout)
    self_check = None
    try:
        self_check = await _probe_wings_until_ready(config_path, timeout=10.0)
    except Exception as exc:
        self_check = {"ok": False, "error": str(exc)[:200]}

    result = {
        "cert_id": cert_id,
        "fingerprint_sha256": _fingerprint(cert),
        "not_before": _utc_datetime(cert, "not_valid_before"),
        "not_after": _utc_datetime(cert, "not_valid_after"),
        "written": written,
        "restart_result": restart_result,
        "self_check": self_check,
    }
    if restart_result.get("rc") != 0:
        raise CertificateError(
            f"wings restart failed rc={restart_result.get('rc')}: "
            f"{restart_result.get('stderr') or restart_result.get('stdout') or ''}"
        )
    return result
