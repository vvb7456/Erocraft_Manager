"""Dev-only helper: manually fire + resolve a HostAlert to verify the new
`monitoring.alert.{fired,resolved}` audit rows land in `manager_activity_logs`.

Usage:
    venv/bin/python -m app.scripts.dev_trigger_alert <host_id>

Does NOT send email (passes config=None to _raise_or_skip / _auto_resolve).
"""
from __future__ import annotations

import asyncio
import sys

from app.core.time import utc_naive_now
from app.db.session import get_session_factory
from app.jobs.tasks.monitoring import _auto_resolve, _raise_or_skip


async def main(host_id: int) -> None:
    Session = get_session_factory()
    async with Session() as db:
        now = utc_naive_now()
        await _raise_or_skip(
            db, host_id, "agent_only_down", "critical",
            f"[dev test] manual fire for host {host_id}", now,
            config=None, host_name=f"dev-host-{host_id}",
        )
        await db.commit()
        print(f"[fired] host={host_id} type=agent_only_down at {now.isoformat()}")

        # Simulate a 7-second outage and resolve.
        await asyncio.sleep(2)
        now2 = utc_naive_now()
        await _auto_resolve(
            db, host_id, "agent_only_down", now2,
            config=None, host_name=f"dev-host-{host_id}",
        )
        await db.commit()
        print(f"[resolved] host={host_id} type=agent_only_down at {now2.isoformat()}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: dev_trigger_alert.py <host_id>", file=sys.stderr)
        sys.exit(2)
    asyncio.run(main(int(sys.argv[1])))
