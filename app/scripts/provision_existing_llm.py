"""One-shot: provision LLM subscriptions for existing active servers.

For every SillyTavern server whose expiration_date >= today (or NULL),
creates a NewAPI per-server user + subscription + token based on the
plan assigned to that server. Servers without an order are assigned
to plan 2 (SillyTavern 标准版) by default.

Usage:
    cd /opt/erocraft_manager/current
    venv/bin/python -m app.scripts.provision_existing_llm --dry-run
    venv/bin/python -m app.scripts.provision_existing_llm

Non-fatal: individual failures are logged and skipped. The final
summary shows success / skip / fail counts.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date

from sqlalchemy import text

from app.db.models.billing import BillingPlan
from app.db.models.manager import ServerLlmKey
from app.db.models.pterodactyl import PteroServer
from app.db.session import get_session_factory
from app.services.llm_provision import provision as llm_provision


async def _fetch_servers(db) -> list[dict]:
    rows = await db.execute(
        text(
            """
            SELECT s.id          AS server_id,
                   s.owner_id    AS owner_id,
                   s.status      AS server_status,
                   m.expiration_date AS expiration_date,
                   o.plan_id     AS plan_id
            FROM servers s
            JOIN eggs e ON s.egg_id = e.id
            LEFT JOIN manager_server_meta m ON m.server_id = s.id
            LEFT JOIN (
                SELECT target_server_id, MAX(id) AS order_id
                FROM manager_billing_orders
                WHERE status = 'applied' AND target_server_id IS NOT NULL
                GROUP BY target_server_id
            ) latest ON latest.target_server_id = s.id
            LEFT JOIN manager_billing_orders o ON o.id = latest.order_id
            WHERE e.name LIKE '%SillyTavern%'
            ORDER BY s.id
            """
        )
    )
    columns = rows.keys()
    return [dict(zip(columns, r)) for r in rows.fetchall()]


async def _load_plan_map(db) -> dict[int, BillingPlan]:
    rows = await db.execute(text("SELECT * FROM manager_billing_plans"))
    columns = list(rows.keys())
    return {r[0]: dict(zip(columns, r)) for r in rows.fetchall()}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Provision LLM for existing servers")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without executing")
    args = parser.parse_args()

    factory = get_session_factory()
    async with factory() as db:
        servers = await _fetch_servers(db)
        plan_map = await _load_plan_map(db)

    today = date.today()
    DEFAULT_PLAN_ID = 2

    targets: list[tuple[int, int, int]] = []  # (server_id, owner_id, plan_id)
    skipped: list[tuple[int, str]] = []

    for srv in servers:
        sid = srv["server_id"]
        exp = srv["expiration_date"]
        if exp is not None and exp < today:
            skipped.append((sid, f"expired {exp}"))
            continue
        plan_id = srv["plan_id"] or DEFAULT_PLAN_ID
        plan = plan_map.get(plan_id)
        if plan is None or not plan.get("llm_enabled") or not plan.get("newapi_plan_id"):
            skipped.append((sid, f"plan {plan_id} has no LLM"))
            continue
        targets.append((sid, srv["owner_id"], plan_id))

    print(f"Total ST servers: {len(servers)}")
    print(f"  To provision:   {len(targets)}")
    print(f"  Skipped:        {len(skipped)}")
    for sid, reason in skipped:
        print(f"    skip {sid}: {reason}")

    if args.dry_run:
        print("\n--dry-run: showing targets only, not executing")
        for sid, uid, pid in targets:
            print(f"  server {sid}  owner={uid}  plan={pid}")
        return

    succeeded = 0
    failed = 0
    for i, (sid, uid, pid) in enumerate(targets, 1):
        plan = plan_map[pid]
        snapshot = {
            "llm_enabled": True,
            "llm_quota_grant": plan["llm_quota_grant"],
            "newapi_plan_id": plan["newapi_plan_id"],
            "llm_group": plan["llm_group"],
        }
        try:
            async with factory() as db:
                row = await db.get(ServerLlmKey, sid)
                if row is not None and row.status == "active":
                    print(f"  [{i}/{len(targets)}] server {sid}: already active, skip")
                    continue
                await llm_provision.provision_for_server(db, sid, uid, snapshot)
                await db.commit()
            print(f"  [{i}/{len(targets)}] server {sid}: OK (plan={pid})")
            succeeded += 1
        except Exception as exc:
            print(f"  [{i}/{len(targets)}] server {sid}: FAIL — {exc}")
            failed += 1
        await asyncio.sleep(1.0)

    print(f"\nDone: {succeeded} succeeded, {failed} failed, {len(skipped)} skipped")


if __name__ == "__main__":
    asyncio.run(main())
