"""One-shot data migration: legacy single-file Flask manager → manager_server_meta.

Reads the legacy manager's SQLite ``server`` table (the **truth source** for
server expiration dates) and upserts each row into the new
``manager_server_meta`` table.

Mapping:
    legacy.server.ptero_server_id  →  manager_server_meta.server_id   (FK panel.servers.id)
    legacy.server.expiration_date  →  manager_server_meta.expiration_date
    (constant)                     →  manager_server_meta.install_notified_at = NOW()
                                       (legacy servers are pre-existing — never
                                        re-notify "install completed" for them)

Safe to re-run: upserts on ``server_id`` PK. Never modifies panel tables.
Skips legacy rows whose ``ptero_server_id`` no longer exists in
``panel.servers`` (deleted in panel but lingering in SQLite cache).

Required env:
    LEGACY_SQLITE  — path to legacy project.db
    DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME — panel db (reused from .env)

Usage:
    python -m app.scripts.migrate_legacy_expiration --dry-run
    python -m app.scripts.migrate_legacy_expiration --apply
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime

import pymysql
from dotenv import load_dotenv


def fetch_legacy_rows(sqlite_path: str) -> list[tuple[int, str, str | None]]:
    conn = sqlite3.connect(sqlite_path)
    try:
        rows = conn.execute(
            "SELECT ptero_server_id, server_name, expiration_date "
            "FROM server "
            "ORDER BY ptero_server_id"
        ).fetchall()
    finally:
        conn.close()
    return rows


def fetch_panel_server_ids(cur: pymysql.cursors.Cursor) -> set[int]:
    cur.execute("SELECT id FROM servers")
    return {row[0] for row in cur.fetchall()}


def fetch_existing_meta(cur: pymysql.cursors.Cursor) -> dict[int, tuple]:
    cur.execute(
        "SELECT server_id, expiration_date, install_notified_at "
        "FROM manager_server_meta"
    )
    return {row[0]: row for row in cur.fetchall()}


def run(sqlite_path: str, apply_changes: bool) -> int:
    load_dotenv()
    mysql_cfg = {
        "host": os.environ["DB_HOST"],
        "port": int(os.environ.get("DB_PORT", "3306")),
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
        "database": os.environ["DB_NAME"],
        "charset": "utf8mb4",
        "autocommit": False,
    }

    legacy = fetch_legacy_rows(sqlite_path)
    print(f"Legacy SQLite: {len(legacy)} rows read from {sqlite_path}")

    conn = pymysql.connect(**mysql_cfg)
    try:
        with conn.cursor() as cur:
            panel_ids = fetch_panel_server_ids(cur)
            existing = fetch_existing_meta(cur)
            print(
                f"Panel servers: {len(panel_ids)} | "
                f"existing manager_server_meta rows: {len(existing)}"
            )

            to_insert: list[tuple[int, str | None]] = []
            to_update: list[tuple[int, str | None]] = []
            skipped_missing: list[tuple[int, str]] = []
            skipped_same: list[int] = []

            for ptero_id, name, exp in legacy:
                if ptero_id not in panel_ids:
                    skipped_missing.append((ptero_id, name))
                    continue
                cur_row = existing.get(ptero_id)
                if cur_row is None:
                    to_insert.append((ptero_id, exp))
                else:
                    cur_exp = cur_row[1]
                    # cur_exp may be a datetime.date or None
                    cur_exp_str = cur_exp.isoformat() if cur_exp else None
                    if cur_exp_str == exp:
                        skipped_same.append(ptero_id)
                    else:
                        to_update.append((ptero_id, exp))

            print()
            print(f"  to insert: {len(to_insert)}")
            print(f"  to update: {len(to_update)}")
            print(f"  skipped (panel server missing): {len(skipped_missing)}")
            print(f"  skipped (already same): {len(skipped_same)}")

            if skipped_missing:
                print()
                print("  rows skipped because ptero_server_id not in panel.servers:")
                for pid, nm in skipped_missing[:20]:
                    print(f"    ptero_server_id={pid} name={nm!r}")
                if len(skipped_missing) > 20:
                    print(f"    ... +{len(skipped_missing) - 20} more")

            if not apply_changes:
                print()
                print("DRY-RUN — no changes written. Pass --apply to commit.")
                return 0

            now = datetime.utcnow().replace(microsecond=0)
            inserted = 0
            updated = 0

            for server_id, exp in to_insert:
                cur.execute(
                    "INSERT INTO manager_server_meta "
                    "(server_id, expiration_date, plan_id, install_notified_at) "
                    "VALUES (%s, %s, NULL, %s)",
                    (server_id, exp, now),
                )
                inserted += 1

            for server_id, exp in to_update:
                cur.execute(
                    "UPDATE manager_server_meta "
                    "SET expiration_date = %s, install_notified_at = "
                    "COALESCE(install_notified_at, %s) "
                    "WHERE server_id = %s",
                    (exp, now, server_id),
                )
                updated += 1

            conn.commit()
            print()
            print(f"APPLIED — inserted={inserted} updated={updated}")
    finally:
        conn.close()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--sqlite",
        default=os.environ.get("LEGACY_SQLITE", "/tmp/legacy_manager.db"),
        help="path to legacy project.db (default: %(default)s)",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = p.parse_args()
    return run(args.sqlite, apply_changes=args.apply)


if __name__ == "__main__":
    sys.exit(main())
