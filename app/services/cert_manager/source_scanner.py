"""Scan registered local certificate sources."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_naive_now
from app.db.models.manager import ManagerCertificate

from .pem import CertPemError, load_source_material

logger = logging.getLogger(__name__)


async def scan_certificate_source(
    db: AsyncSession,
    cert: ManagerCertificate,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    """Read a certificate's source PEM files and update source metadata."""
    before_fp = cert.source_fingerprint_sha256
    now = utc_naive_now()
    try:
        material = load_source_material(cert.source_path)
    except CertPemError as exc:
        cert.source_last_seen_at = now
        cert.source_last_error = str(exc)
        if commit:
            try:
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return {
            "ok": False,
            "certificate_id": cert.id,
            "changed": False,
            "error": str(exc),
        }

    parsed = material.parsed
    cert.source_fingerprint_sha256 = parsed.fingerprint_sha256
    cert.source_not_before = parsed.not_before
    cert.source_not_after = parsed.not_after
    cert.source_last_seen_at = now
    cert.source_last_error = None
    if commit:
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    changed = before_fp is not None and before_fp != parsed.fingerprint_sha256
    return {
        "ok": True,
        "certificate_id": cert.id,
        "changed": changed,
        "previous_fingerprint_sha256": before_fp,
        "fingerprint_sha256": parsed.fingerprint_sha256,
        "not_before": parsed.not_before,
        "not_after": parsed.not_after,
        "san": parsed.san,
    }


async def scan_all_certificate_sources(db: AsyncSession) -> list[dict[str, Any]]:
    """Scan every enabled registered certificate source."""
    result = await db.execute(
        select(ManagerCertificate.id)
        .where(ManagerCertificate.enabled.is_(True))
        .order_by(ManagerCertificate.id)
    )
    cert_ids = [row[0] for row in result.all()]
    out: list[dict[str, Any]] = []
    for cert_id in cert_ids:
        try:
            cert = await db.get(ManagerCertificate, cert_id)
            if cert is None:
                continue
            out.append(await scan_certificate_source(db, cert))
        except Exception as exc:  # noqa: BLE001
            # MariaDB REPEATABLE-READ can raise error 1020 "Record has
            # changed since last read" when a concurrent cert job modified
            # the same row. Rollback resets the session; re-fetching the
            # cert in the next iteration avoids accessing expired ORM
            # attributes on a degraded session (which would cascade into
            # MissingGreenlet / PendingRollbackError).
            await db.rollback()
            logger.warning("cert source scan crashed cert_id=%s: %s", cert_id, exc)
            out.append({
                "ok": False,
                "certificate_id": cert_id,
                "changed": False,
                "error": str(exc),
            })
    return out
