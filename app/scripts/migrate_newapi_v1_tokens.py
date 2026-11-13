"""One-off migration: mint NewAPI v1.0 scoped PATs (``nap_...``) for legacy servers.

Legacy 32-char ``users.access_token`` credentials retire 30 days after NewAPI
v1.0 first boots. Each provisioned server already stores its sub-user password
in ``manager_server_llm_keys.newapi_user_password``, so this script logs in as
each legacy server sub-user, mints a non-expiring minimal-scope ``nap_...`` PAT,
verifies it can read the server's API key metadata, and updates
``newapi_user_access_token`` in place without touching any customer ``sk-...``
API keys. Safe to interrupt and re-run (rows already starting with ``nap_`` are
skipped).

Usage:
    venv/bin/python -m app.scripts.migrate_newapi_v1_tokens --dry-run
    venv/bin/python -m app.scripts.migrate_newapi_v1_tokens --server-id 1101
    venv/bin/python -m app.scripts.migrate_newapi_v1_tokens
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import sys

from sqlalchemy import select, update

from app.db.models.manager import ServerLlmKey
from app.db.session import dispose_engine, get_session_factory
from app.services.llm_provision import newapi_client


@dataclass(frozen=True)
class _PendingServer:
    server_id: int
    newapi_user_id: int
    newapi_user_password: str
    status: str


async def _migrate(
    *, dry_run: bool, server_id: int | None, delay: float
) -> int:
    session_factory = get_session_factory()
    try:
        async with session_factory() as db:
            stmt = (
                select(ServerLlmKey)
                .where(ServerLlmKey.status != "revoked")
                .order_by(ServerLlmKey.server_id.asc())
            )
            if server_id is not None:
                stmt = stmt.where(ServerLlmKey.server_id == server_id)

            rows = (await db.execute(stmt)).scalars().all()
            total_count = len(rows)
            pending = [
                _PendingServer(
                    server_id=row.server_id,
                    newapi_user_id=row.newapi_user_id,
                    newapi_user_password=row.newapi_user_password or "",
                    status=row.status,
                )
                for row in rows
                if not (row.newapi_user_access_token or "").startswith("nap_")
            ]

        already_migrated = total_count - len(pending)
        print(
            f"total={total_count} already_nap={already_migrated} pending={len(pending)}"
        )

        if dry_run or not pending:
            for item in pending:
                has_pw = bool(item.newapi_user_password)
                print(
                    f"  [dry-run] server_id={item.server_id} "
                    f"newapi_user_id={item.newapi_user_id} status={item.status} "
                    f"has_password={has_pw}"
                )
            return 0

        succeeded = 0
        failed = 0
        for idx, item in enumerate(pending, start=1):
            if not item.newapi_user_password:
                print(
                    f"[{idx}/{len(pending)}] FAIL server_id={item.server_id}: "
                    "empty newapi_user_password",
                    file=sys.stderr,
                )
                failed += 1
                continue

            try:
                async with session_factory() as db:
                    user_resp = await newapi_client.get_user(db, item.newapi_user_id)
                    user_data = user_resp.get("data")
                    username = (
                        str(user_data["username"])
                        if isinstance(user_data, dict) and user_data.get("username")
                        else f"srv_{item.server_id}"
                    )

                    new_pat = await newapi_client.login_and_gen_access_token(
                        db,
                        username=username,
                        password=item.newapi_user_password,
                    )
                    if not new_pat.startswith("nap_"):
                        raise newapi_client.NewApiError(
                            f"unexpected token prefix: {new_pat[:6]!r}"
                        )

                    # Verify the newly minted PAT works on a read-only token lookup
                    # before overwriting the stored credential.
                    await newapi_client.find_token_by_name(
                        db,
                        access_token=new_pat,
                        user_id=item.newapi_user_id,
                        name=f"srv_{item.server_id}",
                    )

                    await db.execute(
                        update(ServerLlmKey)
                        .where(
                            ServerLlmKey.server_id == item.server_id,
                            ServerLlmKey.status != "revoked",
                        )
                        .values(newapi_user_access_token=new_pat)
                    )
                    await db.commit()

                succeeded += 1
                print(
                    f"[{idx}/{len(pending)}] OK   server_id={item.server_id} "
                    f"user={username} ({item.newapi_user_id})"
                )
            except Exception as exc:
                failed += 1
                print(
                    f"[{idx}/{len(pending)}] FAIL server_id={item.server_id} "
                    f"newapi_user_id={item.newapi_user_id}: {exc}",
                    file=sys.stderr,
                )

            if delay > 0 and idx < len(pending):
                await asyncio.sleep(delay)

        print(f"done: succeeded={succeeded} failed={failed}")
        return 1 if failed else 0
    finally:
        await newapi_client.close_client()
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate server LLM sub-users from legacy tokens to NewAPI v1.0 nap_ PATs."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List pending rows without calling NewAPI or writing DB.",
    )
    parser.add_argument(
        "--server-id",
        type=int,
        default=None,
        help="Only migrate a single server_id (useful for smoke testing).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.2,
        help="Delay in seconds between servers (default: 0.2).",
    )
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            _migrate(
                dry_run=args.dry_run,
                server_id=args.server_id,
                delay=args.delay,
            )
        )
    )


if __name__ == "__main__":
    main()
