"""Certificate status and install helpers for wings TLS files."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from ..config import CertInstallTargetFile, CertInstallTargetDSM
from ..utils.atomic import atomic_write_bytes
from . import wings, wings_config, wings_service


class CertificateError(Exception):
    """Raised when certificate status or installation cannot proceed."""


SYNO_WEBAPI = "/usr/syno/bin/synowebapi"
SYNO_CERT_ARCHIVE = Path("/usr/syno/etc/certificate/_archive")
SUPPORTED_DSM_VERSION = ("7.2.1", "69057", "1")


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


def _read_dsm_version() -> dict[str, str]:
    version_path = Path("/etc.defaults/VERSION")
    try:
        raw = version_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise CertificateError(f"failed to read DSM version: {exc}") from exc

    values: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def _ensure_supported_dsm() -> None:
    values = _read_dsm_version()
    actual = (
        values.get("productversion") or "",
        values.get("buildnumber") or "",
        values.get("smallfixnumber") or "0",
    )
    if actual != SUPPORTED_DSM_VERSION:
        raise CertificateError(
            "unsupported DSM version: "
            f"{actual[0]}-{actual[1]} Update {actual[2]} "
            f"(expected {SUPPORTED_DSM_VERSION[0]}-{SUPPORTED_DSM_VERSION[1]} "
            f"Update {SUPPORTED_DSM_VERSION[2]})"
        )


def _extract_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise CertificateError(f"synowebapi returned no JSON object: {text[:200]}")
    try:
        payload = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise CertificateError(f"synowebapi returned invalid JSON: {text[:200]}") from exc
    if not isinstance(payload, dict):
        raise CertificateError("synowebapi returned non-object JSON")
    return payload


async def _run_synowebapi(
    *,
    api: str,
    method: str,
    version: int = 1,
    params: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    if not Path(SYNO_WEBAPI).exists():
        raise CertificateError(f"synowebapi not found: {SYNO_WEBAPI}")

    args = [
        SYNO_WEBAPI,
        "--exec",
        f"api={api}",
        f"method={method}",
        f"version={version}",
    ]
    for key, value in (params or {}).items():
        args.append(f"{key}={json.dumps(value)}")

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise CertificateError(f"synowebapi {api}.{method} timed out") from exc

    stdout = out.decode("utf-8", "replace")
    stderr = err.decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        raise CertificateError(
            f"synowebapi {api}.{method} rc={proc.returncode}: "
            f"{stderr or stdout[:300]}"
        )
    payload = _extract_json_object(stdout)
    if not payload.get("success"):
        code = None
        error = payload.get("error")
        if isinstance(error, dict):
            code = error.get("code")
        raise CertificateError(
            f"synowebapi {api}.{method} failed"
            + (f" code={code}" if code is not None else "")
        )
    return payload


async def _synology_certificates(timeout: float = 15.0) -> list[dict[str, Any]]:
    _ensure_supported_dsm()
    payload = await _run_synowebapi(
        api="SYNO.Core.Certificate.CRT",
        method="list",
        timeout=timeout,
    )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    certs = data.get("certificates") if isinstance(data, dict) else None
    if not isinstance(certs, list):
        raise CertificateError("DSM certificate list missing data.certificates")
    return [item for item in certs if isinstance(item, dict)]


def _synology_domains(item: dict[str, Any]) -> list[str]:
    subject = item.get("subject") if isinstance(item.get("subject"), dict) else {}
    domains: list[str] = []
    common_name = subject.get("common_name") if isinstance(subject, dict) else None
    if common_name:
        domains.append(str(common_name))
    san = subject.get("sub_alt_name") if isinstance(subject, dict) else None
    if isinstance(san, list):
        domains.extend(str(item) for item in san if item)
    return sorted(set(domains))


def _find_synology_certificate(
    target: CertInstallTargetDSM,
    certs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    wanted = target.synology.certificate_desc.strip()
    for item in certs:
        if str(item.get("desc") or "") == wanted:
            return item
    wanted_lower = wanted.lower()
    for item in certs:
        if any(domain.lower() == wanted_lower for domain in _synology_domains(item)):
            return item
    return None


def _parse_dsm_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%b %d %H:%M:%S %Y GMT")
    except ValueError:
        return None


def _synology_archive_cert_summary(cert_id: str) -> dict[str, Any] | None:
    # DSM's own archive is read-only from our perspective. Import still goes
    # through DSM WebAPI; this read is only to compute fingerprint/status.
    for name in ("cert.pem", "fullchain.pem"):
        path = SYNO_CERT_ARCHIVE / cert_id / name
        if not path.exists():
            continue
        try:
            return _cert_summary(path)
        except (CertificateError, OSError):
            continue
    return None


def _synology_status_from_item(item: dict[str, Any]) -> dict[str, Any]:
    cert_id = str(item.get("id") or "")
    domains = _synology_domains(item)
    current_cert = _synology_archive_cert_summary(cert_id) if cert_id else None
    if current_cert is None:
        current_cert = {
            "fingerprint_sha256": None,
            "file_sha256": None,
            "subject": f"CN={domains[0]}" if domains else None,
            "san": domains,
            "not_before": _parse_dsm_time(item.get("valid_from")),
            "not_after": _parse_dsm_time(item.get("valid_till")),
        }
    return {
        "dsm_cert_id": cert_id,
        "is_default": bool(item.get("is_default")),
        "domains": domains,
        "services": item.get("services") if isinstance(item.get("services"), list) else [],
        "current_cert": current_cert,
    }


async def _target_status_one(target: Any) -> dict[str, Any]:
    if isinstance(target, CertInstallTargetDSM):
        base: dict[str, Any] = {
            "name": target.name,
            "type": "synology_dsm",
            "certificate_desc": target.synology.certificate_desc,
            "exists": False,
            "current_cert": None,
        }
        try:
            certs = await _synology_certificates()
            item = _find_synology_certificate(target, certs)
            if item is None:
                base["error"] = (
                    "DSM certificate not found: "
                    f"{target.synology.certificate_desc}"
                )
                return base
            base["exists"] = True
            base.update(_synology_status_from_item(item))
            return base
        except CertificateError as exc:
            base["error"] = str(exc)
            return base

    # CertInstallTargetFile
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


def _split_certificate_chain(fullchain: bytes) -> tuple[bytes, bytes]:
    blocks = re.findall(
        rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----\s*",
        fullchain,
        flags=re.DOTALL,
    )
    if not blocks:
        raise CertificateError("invalid fullchain PEM: no certificate blocks")
    leaf = blocks[0]
    chain = b"".join(blocks[1:])
    return leaf, chain


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

    if isinstance(target, CertInstallTargetDSM):
        return await _install_synology_target(
            target=target,
            cert_id=cert_id,
            fullchain_pem=fullchain_pem,
            privkey_pem=privkey_pem,
            timeout=timeout,
        )

    # CertInstallTargetFile
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


async def _install_synology_target(
    *,
    target: CertInstallTargetDSM,
    cert_id: int | None,
    fullchain_pem: str,
    privkey_pem: str,
    timeout: float,
) -> dict[str, Any]:
    _ensure_supported_dsm()
    fullchain, privkey, cert = _validate_install_payload(fullchain_pem, privkey_pem)
    leaf, chain = _split_certificate_chain(fullchain)

    certs = await _synology_certificates(timeout=min(timeout, 15.0))
    existing = _find_synology_certificate(target, certs)
    if existing is None:
        if target.synology.create_if_missing:
            raise CertificateError(
                "synology_dsm create_if_missing is not supported on this runner"
            )
        raise CertificateError(
            "DSM certificate not found: "
            f"{target.synology.certificate_desc}"
        )

    dsm_cert_id = str(existing.get("id") or "")
    if not dsm_cert_id:
        raise CertificateError("DSM certificate has no id")

    with tempfile.TemporaryDirectory(
        prefix="erocraft-dsm-cert-",
        dir="/tmp",
    ) as tmp_dir_raw:
        tmp_dir = Path(tmp_dir_raw)
        os.chmod(tmp_dir, 0o700)
        key_path = tmp_dir / "privkey.pem"
        cert_path = tmp_dir / "cert.pem"
        chain_path = tmp_dir / "chain.pem"
        key_path.write_bytes(privkey)
        cert_path.write_bytes(leaf)
        chain_path.write_bytes(chain)
        os.chmod(key_path, 0o600)
        os.chmod(cert_path, 0o600)
        os.chmod(chain_path, 0o600)

        params: dict[str, Any] = {
            "key_tmp": str(key_path),
            "cert_tmp": str(cert_path),
            "inter_cert_tmp": str(chain_path),
            "id": dsm_cert_id,
            "desc": target.synology.certificate_desc,
        }
        if target.synology.as_default:
            # DSM 7.2.1 import expects this as a form-style string, not JSON bool.
            params["as_default"] = "true"

        response = await _run_synowebapi(
            api="SYNO.Core.Certificate",
            method="import",
            params=params,
            timeout=timeout,
        )

    dsm_status: dict[str, Any] | None = None
    try:
        refreshed = await _synology_certificates(timeout=min(timeout, 15.0))
        refreshed_item = next(
            (item for item in refreshed if str(item.get("id") or "") == dsm_cert_id),
            None,
        )
        if refreshed_item is not None:
            dsm_status = _synology_status_from_item(refreshed_item)
    except CertificateError:
        dsm_status = None

    return {
        "cert_id": cert_id,
        "target_name": target.name,
        "target_type": "synology_dsm",
        "dsm_cert_id": dsm_cert_id,
        "fingerprint_sha256": _fingerprint(cert),
        "not_before": _utc_datetime(cert, "not_valid_before"),
        "not_after": _utc_datetime(cert, "not_valid_after"),
        "synowebapi": {
            "httpd_restart": bool(response.get("httpd_restart")),
            "restart_httpd": bool(
                (response.get("data") or {}).get("restart_httpd")
                if isinstance(response.get("data"), dict)
                else False
            ),
        },
        "dsm_status": dsm_status,
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
