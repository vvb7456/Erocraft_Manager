"""Backfill Panel server descriptions from manager_server_meta expiration dates."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import PteroServer, ServerMeta
from app.db.session import dispose_engine, get_session_factory
from app.services import server_lifecycle
from app.services.server_lifecycle import LifecycleError

logger = logging.getLogger(__name__)


async def run_backfill() -> int:
    session_factory = get_session_factory()
    synced = 0
    failed = 0

    async with session_factory() as db:
        result = await db.execute(
            select(PteroServer)
            .join(ServerMeta, ServerMeta.server_id == PteroServer.id)
            .options(selectinload(PteroServer.meta))
            .order_by(PteroServer.id.asc())
        )
        servers = list(result.scalars().all())

        for server in servers:
            try:
                await server_lifecycle.update_server_expiration_description(
                    db, server.id, server.expiration_date
                )
                await db.commit()
                synced += 1
            except LifecycleError:
                await db.rollback()
                failed += 1
                logger.exception("Failed to sync expiration description for server %s", server.id)

    print(f"Synced {synced} servers; failed {failed} servers.")
    return 1 if failed else 0


async def _main() -> int:
    try:
        return await run_backfill()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))