"""PEM parsing helpers for Manager-owned certificate services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization import load_pem_private_key


class CertPemError(Exception):
    """Raised when source certificate material is missing or invalid."""


@dataclass(frozen=True, slots=True)
class ParsedCertificate:
    fingerprint_sha256: str
    subject: str
    san: list[str]
    not_before: datetime
    not_after: datetime


@dataclass(frozen=True, slots=True)
class SourceMaterial:
    source_path: str
    fullchain_path: str
    privkey_path: str
    fullchain_pem: str
    privkey_pem: str
    parsed: ParsedCertificate


def _to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _cert_not_before(cert: x509.Certificate) -> datetime:
    value = getattr(cert, "not_valid_before_utc", None)
    return _to_naive_utc(value if value is not None else cert.not_valid_before)


def _cert_not_after(cert: x509.Certificate) -> datetime:
    value = getattr(cert, "not_valid_after_utc", None)
    return _to_naive_utc(value if value is not None else cert.not_valid_after)


def _load_cert(fullchain: bytes) -> x509.Certificate:
    try:
        return x509.load_pem_x509_certificate(fullchain)
    except ValueError as exc:
        raise CertPemError("invalid fullchain.pem: no leaf certificate") from exc


def _load_key(privkey: bytes) -> PrivateKeyTypes:
    try:
        return load_pem_private_key(privkey, password=None)
    except (TypeError, ValueError) as exc:
        raise CertPemError("invalid privkey.pem") from exc


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


def parse_material(fullchain: bytes, privkey: bytes) -> ParsedCertificate:
    cert = _load_cert(fullchain)
    key = _load_key(privkey)
    if _cert_public_key_bytes(cert) != _public_key_bytes(key):
        raise CertPemError("fullchain.pem and privkey.pem do not match")

    san: list[str] = []
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        san = list(ext.value.get_values_for_type(x509.DNSName))
    except x509.ExtensionNotFound:
        san = []

    return ParsedCertificate(
        fingerprint_sha256=cert.fingerprint(SHA256()).hex(),
        subject=cert.subject.rfc4514_string(),
        san=san,
        not_before=_cert_not_before(cert),
        not_after=_cert_not_after(cert),
    )


def load_source_material(source_path: str) -> SourceMaterial:
    root = Path(source_path)
    candidates: list[tuple[Path, Path]] = [
        (root / "fullchain.pem", root / "privkey.pem"),
        (root / "fullchain.pem", root / "key.pem"),
    ]
    key_files = sorted(root.glob("*.key")) if root.exists() else []
    if key_files:
        candidates.append((root / "fullchain.cer", key_files[0]))

    selected: tuple[Path, Path] | None = None
    for fullchain_candidate, key_candidate in candidates:
        if fullchain_candidate.exists() and key_candidate.exists():
            selected = (fullchain_candidate, key_candidate)
            break
    if selected is None:
        selected = candidates[0]
    fullchain_path, privkey_path = selected
    try:
        fullchain = fullchain_path.read_bytes()
        privkey = privkey_path.read_bytes()
    except OSError as exc:
        raise CertPemError(f"failed to read source PEM files: {exc}") from exc
    parsed = parse_material(fullchain, privkey)
    return SourceMaterial(
        source_path=str(root),
        fullchain_path=str(fullchain_path),
        privkey_path=str(privkey_path),
        fullchain_pem=fullchain.decode("utf-8", "replace"),
        privkey_pem=privkey.decode("utf-8", "replace"),
        parsed=parsed,
    )
