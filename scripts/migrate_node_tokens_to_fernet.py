#!/usr/bin/env python3
"""Idempotent in-place migration of nodes.daemon_token from Laravel AES-CBC to Fernet.

Usage examples (from repo root or /opt/erocraft_manager/current):
    venv/bin/python scripts/migrate_node_tokens_to_fernet.py --dry-run
    venv/bin/python scripts/migrate_node_tokens_to_fernet.py --apply --backup-confirmed
    venv/bin/python scripts/migrate_node_tokens_to_fernet.py --apply --backup-confirmed --verify-wings
    venv/bin/python scripts/migrate_node_tokens_to_fernet.py --verify-wings
"""

from __future__ import annotations

import argparse
import asyncio
import hmac
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

_env_file = PROJECT_ROOT / ".env"
if _env_file.is_file():
    load_dotenv(_env_file, override=False)

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.node_crypto import (
    NodeTokenCryptoError,
    decrypt_node_token,
    detect_node_token_format,
    encrypt_node_token,
    is_fernet_token,
)
from app.db.models.manager import ManagerHost
from app.db.models.pterodactyl import PanelNode
from app.db.session import dispose_engine, get_session_factory


@dataclass(slots=True)
class NodeMigrationOutcome:
    node_id: int
    node_name: str
    old_format: str
    new_format: str
    old_len: int
    new_len: int
    plaintext_len: int | None
    action: str
    ok: bool
    error: str | None = None


@dataclass(slots=True)
class WingsVerifyOutcome:
    node_id: int
    node_name: str
    host_id: int
    host_name: str
    token_format: str
    http_status: int | None
    version: str | None
    ok: bool
    skipped: bool = False
    error: str | None = None


async def inspect_nodes_dry_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[NodeMigrationOutcome]:
    outcomes: list[NodeMigrationOutcome] = []
    async with session_factory() as session:
        nodes = (
            await session.execute(select(PanelNode).order_by(PanelNode.id.asc()))
        ).scalars().all()

    for node in nodes:
        ciphertext = node.daemon_token or ""
        fmt = detect_node_token_format(ciphertext)
        old_len = len(ciphertext)

        if fmt == "fernet":
            try:
                plaintext = decrypt_node_token(ciphertext)
            except NodeTokenCryptoError as exc:
                outcomes.append(
                    NodeMigrationOutcome(
                        node_id=node.id,
                        node_name=node.name,
                        old_format=fmt,
                        new_format=fmt,
                        old_len=old_len,
                        new_len=old_len,
                        plaintext_len=None,
                        action="failed",
                        ok=False,
                        error=str(exc),
                    )
                )
                continue
            outcomes.append(
                NodeMigrationOutcome(
                    node_id=node.id,
                    node_name=node.name,
                    old_format="fernet",
                    new_format="fernet",
                    old_len=old_len,
                    new_len=old_len,
                    plaintext_len=len(plaintext),
                    action="already_fernet",
                    ok=True,
                )
            )
            continue

        if fmt == "laravel":
            try:
                plaintext = decrypt_node_token(ciphertext)
                candidate = encrypt_node_token(plaintext)
                if not is_fernet_token(candidate):
                    raise NodeTokenCryptoError("生成的密文不是标准 Fernet 格式")
                roundtrip = decrypt_node_token(candidate)
                if not hmac.compare_digest(roundtrip, plaintext):
                    raise NodeTokenCryptoError("Fernet 往返校验明文不一致")
            except NodeTokenCryptoError as exc:
                outcomes.append(
                    NodeMigrationOutcome(
                        node_id=node.id,
                        node_name=node.name,
                        old_format="laravel",
                        new_format="laravel",
                        old_len=old_len,
                        new_len=old_len,
                        plaintext_len=None,
                        action="failed",
                        ok=False,
                        error=str(exc),
                    )
                )
                continue
            outcomes.append(
                NodeMigrationOutcome(
                    node_id=node.id,
                    node_name=node.name,
                    old_format="laravel",
                    new_format="fernet",
                    old_len=old_len,
                    new_len=len(candidate),
                    plaintext_len=len(plaintext),
                    action="pending_migration",
                    ok=True,
                )
            )
            continue

        outcomes.append(
            NodeMigrationOutcome(
                node_id=node.id,
                node_name=node.name,
                old_format="unknown",
                new_format="unknown",
                old_len=old_len,
                new_len=old_len,
                plaintext_len=None,
                action="failed",
                ok=False,
                error="无法识别的密文格式",
            )
        )

    return outcomes


async def apply_node_migrations(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[NodeMigrationOutcome]:
    outcomes: list[NodeMigrationOutcome] = []
    async with session_factory() as session:
        node_rows = (
            await session.execute(
                select(PanelNode.id, PanelNode.name).order_by(PanelNode.id.asc())
            )
        ).all()

    for node_id, node_name in node_rows:
        old_format = "unknown"
        old_len = 0
        try:
            async with session_factory() as session:
                async with session.begin():
                    node = (
                        await session.execute(
                            select(PanelNode)
                            .where(PanelNode.id == node_id)
                            .with_for_update()
                        )
                    ).scalar_one_or_none()
                    if node is None:
                        raise NodeTokenCryptoError(f"节点 {node_id} 在事务中不存在")

                    ciphertext = node.daemon_token or ""
                    old_format = detect_node_token_format(ciphertext)
                    old_len = len(ciphertext)

                    if old_format == "fernet":
                        plaintext = decrypt_node_token(ciphertext)
                        outcomes.append(
                            NodeMigrationOutcome(
                                node_id=node.id,
                                node_name=node.name,
                                old_format="fernet",
                                new_format="fernet",
                                old_len=old_len,
                                new_len=old_len,
                                plaintext_len=len(plaintext),
                                action="already_fernet",
                                ok=True,
                            )
                        )
                        continue

                    if old_format != "laravel":
                        raise NodeTokenCryptoError("无法识别的密文格式，拒绝原地转码")

                    plaintext = decrypt_node_token(ciphertext)
                    new_ciphertext = encrypt_node_token(plaintext)
                    if not is_fernet_token(new_ciphertext):
                        raise NodeTokenCryptoError("生成的密文不是标准 Fernet 格式")
                    if not hmac.compare_digest(decrypt_node_token(new_ciphertext), plaintext):
                        raise NodeTokenCryptoError("写入前 Fernet 往返校验失败")

                    await session.execute(
                        update(PanelNode)
                        .where(PanelNode.id == node_id)
                        .values(daemon_token=new_ciphertext)
                    )

                    # Read back directly from DB before commit to verify storage integrity.
                    stored = (
                        await session.execute(
                            select(PanelNode.daemon_token).where(PanelNode.id == node_id)
                        )
                    ).scalar_one()
                    if stored != new_ciphertext or not is_fernet_token(stored):
                        raise NodeTokenCryptoError("写后回读密文与预期不一致")
                    if not hmac.compare_digest(decrypt_node_token(stored), plaintext):
                        raise NodeTokenCryptoError("写后回读解密明文不一致")

                    outcomes.append(
                        NodeMigrationOutcome(
                            node_id=node.id,
                            node_name=node.name,
                            old_format="laravel",
                            new_format="fernet",
                            old_len=old_len,
                            new_len=len(stored),
                            plaintext_len=len(plaintext),
                            action="migrated",
                            ok=True,
                        )
                    )
        except Exception as exc:
            outcomes.append(
                NodeMigrationOutcome(
                    node_id=node_id,
                    node_name=node_name,
                    old_format=old_format,
                    new_format=old_format,
                    old_len=old_len,
                    new_len=old_len,
                    plaintext_len=None,
                    action="failed",
                    ok=False,
                    error=str(exc),
                )
            )
            break

    return outcomes


async def verify_wings_nodes(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    timeout: float = 10.0,
    include_disabled: bool = False,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> list[WingsVerifyOutcome]:
    outcomes: list[WingsVerifyOutcome] = []
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(PanelNode, ManagerHost)
                .join(ManagerHost, ManagerHost.pterodactyl_node_id == PanelNode.id)
                .where(
                    ManagerHost.kind == "wings_node",
                    ManagerHost.pterodactyl_node_id.is_not(None),
                )
                .order_by(PanelNode.id.asc())
            )
        ).all()

    factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout, trust_env=False))
    async with factory() as client:
        for node, host in rows:
            token_format = detect_node_token_format(node.daemon_token or "")
            if not include_disabled and not host.enabled:
                outcomes.append(
                    WingsVerifyOutcome(
                        node_id=node.id,
                        node_name=node.name,
                        host_id=host.id,
                        host_name=host.name,
                        token_format=token_format,
                        http_status=None,
                        version=None,
                        ok=True,
                        skipped=True,
                    )
                )
                continue

            try:
                # Freshly decrypt from DB row (never using WingsService cache).
                plaintext = decrypt_node_token(node.daemon_token)
            except NodeTokenCryptoError as exc:
                outcomes.append(
                    WingsVerifyOutcome(
                        node_id=node.id,
                        node_name=node.name,
                        host_id=host.id,
                        host_name=host.name,
                        token_format=token_format,
                        http_status=None,
                        version=None,
                        ok=False,
                        error=str(exc),
                    )
                )
                continue

            url = f"{node.scheme}://{node.fqdn}:{node.daemon_listen}/api/system"
            headers = {
                "Authorization": f"Bearer {plaintext}",
                "Accept": "application/json",
            }
            try:
                response = await client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                outcomes.append(
                    WingsVerifyOutcome(
                        node_id=node.id,
                        node_name=node.name,
                        host_id=host.id,
                        host_name=host.name,
                        token_format=token_format,
                        http_status=None,
                        version=None,
                        ok=False,
                        error=f"Wings 请求失败: {type(exc).__name__}",
                    )
                )
                continue

            if response.status_code != 200:
                outcomes.append(
                    WingsVerifyOutcome(
                        node_id=node.id,
                        node_name=node.name,
                        host_id=host.id,
                        host_name=host.name,
                        token_format=token_format,
                        http_status=response.status_code,
                        version=None,
                        ok=False,
                        error=f"HTTP {response.status_code}",
                    )
                )
                continue

            version = "unknown"
            try:
                body = response.json()
                if isinstance(body, dict) and body.get("version"):
                    version = str(body["version"])
            except ValueError:
                pass

            outcomes.append(
                WingsVerifyOutcome(
                    node_id=node.id,
                    node_name=node.name,
                    host_id=host.id,
                    host_name=host.name,
                    token_format=token_format,
                    http_status=response.status_code,
                    version=version,
                    ok=True,
                )
            )

    return outcomes


def _print_migration_report(outcomes: list[NodeMigrationOutcome], *, mode: str) -> None:
    print(f"=== nodes.daemon_token {mode} ===")
    for item in outcomes:
        status = "OK" if item.ok else "FAIL"
        pt_len = item.plaintext_len if item.plaintext_len is not None else "-"
        line = (
            f"[{status}] node_id={item.node_id} name={item.node_name} "
            f"format={item.old_format}->{item.new_format} "
            f"len={item.old_len}->{item.new_len} plaintext_len={pt_len} "
            f"action={item.action}"
        )
        if item.error:
            line += f" error={item.error}"
        print(line)

    total = len(outcomes)
    already = sum(1 for o in outcomes if o.action == "already_fernet")
    pending = sum(1 for o in outcomes if o.action == "pending_migration")
    migrated = sum(1 for o in outcomes if o.action == "migrated")
    failed = sum(1 for o in outcomes if not o.ok)
    print(
        f"Summary ({mode}): total={total} already_fernet={already} "
        f"pending={pending} migrated={migrated} failed={failed}"
    )


def _print_wings_verify_report(outcomes: list[WingsVerifyOutcome]) -> None:
    print("=== Wings GET /api/system verification ===")
    for item in outcomes:
        if item.skipped:
            print(
                f"[SKIP] node_id={item.node_id} name={item.node_name} "
                f"host_id={item.host_id} host_name={item.host_name} "
                f"format={item.token_format} reason=host_disabled"
            )
            continue
        status = "OK" if item.ok else "FAIL"
        http_str = str(item.http_status) if item.http_status is not None else "-"
        ver_str = item.version or "-"
        line = (
            f"[{status}] node_id={item.node_id} name={item.node_name} "
            f"host_id={item.host_id} host_name={item.host_name} "
            f"format={item.token_format} http={http_str} wings_version={ver_str}"
        )
        if item.error:
            line += f" error={item.error}"
        print(line)

    checked = [o for o in outcomes if not o.skipped]
    passed = sum(1 for o in checked if o.ok)
    failed = sum(1 for o in checked if not o.ok)
    skipped = sum(1 for o in outcomes if o.skipped)
    print(f"Summary (verify-wings): checked={len(checked)} passed={passed} failed={failed} skipped={skipped}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="将 nodes.daemon_token 从 Laravel 密文原地转码为 Fernet，并可选验证 Wings 通信。"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只读扫描全部节点密文格式、校验 Laravel MAC 与 Fernet 往返，不修改数据库。",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="正式原地转码所有 Laravel 密文节点为 Fernet（必须配合 --backup-confirmed）。",
    )
    parser.add_argument(
        "--backup-confirmed",
        action="store_true",
        help="确认已完成 nodes 表备份；仅与 --apply 配合使用。",
    )
    parser.add_argument(
        "--verify-wings",
        action="store_true",
        help="对已绑定 manager_hosts 的现役 Wings 节点调用 GET /api/system 验证明文通信。",
    )
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="在 --verify-wings 中同时探测 enabled=False 的绑定节点。",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Wings GET /api/system 请求超时秒数（默认 10.0）。",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    session_factory = get_session_factory()
    exit_code = 0
    try:
        if args.dry_run:
            outcomes = await inspect_nodes_dry_run(session_factory)
            _print_migration_report(outcomes, mode="dry-run")
            if any(not o.ok for o in outcomes):
                return 1

        if args.apply:
            outcomes = await apply_node_migrations(session_factory)
            _print_migration_report(outcomes, mode="apply")
            if any(not o.ok for o in outcomes):
                return 1

        if args.verify_wings:
            verify_outcomes = await verify_wings_nodes(
                session_factory,
                timeout=args.timeout,
                include_disabled=args.include_disabled,
            )
            _print_wings_verify_report(verify_outcomes)
            if any(not o.ok for o in verify_outcomes if not o.skipped):
                exit_code = 1
    finally:
        await dispose_engine()

    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.dry_run and args.apply:
        print("错误：--dry-run 与 --apply 不能同时指定。", file=sys.stderr)
        return 2

    if args.apply and not args.backup_confirmed:
        print(
            "错误：--apply 必须显式配合 --backup-confirmed（请先完成 nodes 表备份）。",
            file=sys.stderr,
        )
        return 2

    if not (args.dry_run or args.apply or args.verify_wings):
        parser.print_help(sys.stderr)
        return 2

    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
