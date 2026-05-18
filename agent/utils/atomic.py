"""Atomic file write helper (durable across crashes via fsync).

Used by certificate and cloudflared config writers so daemon startups can
trust on-disk state even after power loss.
"""

from __future__ import annotations

import os
from pathlib import Path


def atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o644) -> None:
    """Write ``data`` to ``path`` atomically.

    Uses a same-directory temp file + ``os.replace`` so readers never see a
    partial file. ``fsync`` guarantees the bytes hit stable storage before
    the rename, preserving durability across power loss / kernel panic.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        with tmp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_write_text(
    path: Path, text: str, *, mode: int = 0o644, encoding: str = "utf-8"
) -> None:
    atomic_write_bytes(path, text.encode(encoding), mode=mode)
