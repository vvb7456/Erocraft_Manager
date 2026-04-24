"""Repository for ``allocations`` table — read & write helpers used by
the admin allocation router (`/api/admin/nodes/{node_id}/allocations`).

Allocations are pure panel-DB metadata; writing/deleting rows here does
**not** require contacting wings or the agent. The panel itself reuses
the same FK semantics: ``servers.allocation_id`` → primary, and
``allocations.server_id`` → reverse pointer. We never touch
``servers.allocation_id`` here; only manage allocation rows themselves.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from sqlalchemy import String, cast, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db.models.pterodactyl import Allocation, PteroServer, PteroUser


def _now() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


class AllocationRepository:
    # ----- read -----

    async def list_all(
        self,
        db: AsyncSession,
        node_id: int,
        *,
        assigned: bool | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Allocation], int]:
        """Return ``(items, total)`` filtered by ``assigned`` and ``search``.

        ``search`` matches against port (numeric prefix), ip, ip_alias,
        notes, server name, server uuid_short — case-insensitive.
        """
        stmt = (
            select(Allocation)
            .where(Allocation.node_id == node_id)
            .options(joinedload(Allocation.server))
        )
        count_stmt = select(func.count()).select_from(Allocation).where(
            Allocation.node_id == node_id
        )

        if assigned is True:
            stmt = stmt.where(Allocation.server_id.isnot(None))
            count_stmt = count_stmt.where(Allocation.server_id.isnot(None))
        elif assigned is False:
            stmt = stmt.where(Allocation.server_id.is_(None))
            count_stmt = count_stmt.where(Allocation.server_id.is_(None))

        if search:
            needle = f"%{search.strip()}%"
            # Outer-join servers for search across server fields.
            stmt = stmt.outerjoin(PteroServer, Allocation.server_id == PteroServer.id).where(
                or_(
                    Allocation.ip.ilike(needle),
                    Allocation.ip_alias.ilike(needle),
                    Allocation.notes.ilike(needle),
                    cast(Allocation.port, String).ilike(needle),
                    PteroServer.name.ilike(needle),
                    PteroServer.uuid_short.ilike(needle),
                )
            )
            count_stmt = (
                select(func.count(func.distinct(Allocation.id)))
                .select_from(Allocation)
                .outerjoin(PteroServer, Allocation.server_id == PteroServer.id)
                .where(
                    Allocation.node_id == node_id,
                    or_(
                        Allocation.ip.ilike(needle),
                        Allocation.ip_alias.ilike(needle),
                        Allocation.notes.ilike(needle),
                        cast(Allocation.port, String).ilike(needle),
                        PteroServer.name.ilike(needle),
                        PteroServer.uuid_short.ilike(needle),
                    ),
                )
            )
            if assigned is True:
                count_stmt = count_stmt.where(Allocation.server_id.isnot(None))
            elif assigned is False:
                count_stmt = count_stmt.where(Allocation.server_id.is_(None))

        stmt = stmt.order_by(Allocation.ip.asc(), Allocation.port.asc()).limit(limit).offset(offset)

        rows = (await db.execute(stmt)).unique().scalars().all()
        total = (await db.execute(count_stmt)).scalar_one()
        return list(rows), int(total)

    async def summary(self, db: AsyncSession, node_id: int) -> tuple[int, int]:
        """Return ``(assigned, unassigned)`` counts for the node."""
        assigned = (
            await db.execute(
                select(func.count()).select_from(Allocation).where(
                    Allocation.node_id == node_id, Allocation.server_id.isnot(None)
                )
            )
        ).scalar_one()
        unassigned = (
            await db.execute(
                select(func.count()).select_from(Allocation).where(
                    Allocation.node_id == node_id, Allocation.server_id.is_(None)
                )
            )
        ).scalar_one()
        return int(assigned), int(unassigned)

    async def get_owner_names(
        self, db: AsyncSession, owner_ids: Iterable[int]
    ) -> dict[int, str]:
        ids = [i for i in owner_ids if i]
        if not ids:
            return {}
        rows = (
            await db.execute(
                select(PteroUser.id, PteroUser.username).where(PteroUser.id.in_(ids))
            )
        ).all()
        return {int(r[0]): str(r[1]) for r in rows}

    # ----- write -----

    async def existing_ports(
        self, db: AsyncSession, node_id: int, ip: str, ports: Iterable[int]
    ) -> set[int]:
        port_list = list(ports)
        if not port_list:
            return set()
        rows = (
            await db.execute(
                select(Allocation.port).where(
                    Allocation.node_id == node_id,
                    Allocation.ip == ip,
                    Allocation.port.in_(port_list),
                )
            )
        ).all()
        return {int(r[0]) for r in rows}

    async def bulk_create(
        self,
        db: AsyncSession,
        node_id: int,
        ip: str,
        alias: str | None,
        ports: set[int],
    ) -> tuple[list[Allocation], list[tuple[int, str]]]:
        """INSERT one row per port. Pre-existing ``(node_id, ip, port)`` rows
        are skipped (reported in the second tuple element)."""
        if not ports:
            return [], []

        already = await self.existing_ports(db, node_id, ip, ports)
        skipped: list[tuple[int, str]] = [(p, "duplicate") for p in sorted(already)]
        to_create = sorted(ports - already)
        if not to_create:
            return [], skipped

        now = _now()
        new_rows = [
            Allocation(
                node_id=node_id,
                ip=ip,
                ip_alias=alias,
                port=port,
                server_id=None,
                notes=None,
                created_at=now,
                updated_at=now,
            )
            for port in to_create
        ]
        db.add_all(new_rows)
        try:
            await db.flush()
        except IntegrityError as exc:
            # Race: another writer slipped in between our SELECT and INSERT.
            await db.rollback()
            raise exc
        # Re-fetch to ensure ids are populated and freshly attached.
        return new_rows, skipped

    async def get(
        self, db: AsyncSession, node_id: int, allocation_id: int
    ) -> Allocation | None:
        row = await db.get(Allocation, allocation_id)
        if row is None or row.node_id != node_id:
            return None
        return row

    async def delete_one(
        self, db: AsyncSession, node_id: int, allocation_id: int
    ) -> tuple[Allocation | None, str | None]:
        """Returns ``(deleted_row, error_code)``. ``error_code`` is one of
        ``"not_found"`` / ``"in_use"`` / ``None``."""
        row = await self.get(db, node_id, allocation_id)
        if row is None:
            return None, "not_found"
        if row.server_id is not None:
            return row, "in_use"
        snapshot = Allocation(
            id=row.id, node_id=row.node_id, ip=row.ip, port=row.port,
            ip_alias=row.ip_alias, server_id=None, notes=row.notes,
        )
        await db.delete(row)
        await db.flush()
        return snapshot, None

    async def delete_many(
        self, db: AsyncSession, node_id: int, ids: list[int]
    ) -> tuple[list[Allocation], list[Allocation]]:
        """Returns ``(deleted, conflicting)``. If any conflict (wrong node
        or in-use), no rows are deleted — caller must roll back the
        surrounding transaction."""
        if not ids:
            return [], []
        rows = (
            await db.execute(select(Allocation).where(Allocation.id.in_(ids)))
        ).scalars().all()
        rows = list(rows)

        seen_ids = {r.id for r in rows}
        missing = [i for i in ids if i not in seen_ids]
        conflicting = [
            r for r in rows if r.node_id != node_id or r.server_id is not None
        ]

        if missing or conflicting:
            return [], conflicting

        snapshots = [
            Allocation(id=r.id, node_id=r.node_id, ip=r.ip, port=r.port,
                       ip_alias=r.ip_alias, server_id=None, notes=r.notes)
            for r in rows
        ]
        await db.execute(delete(Allocation).where(Allocation.id.in_(ids)))
        await db.flush()
        return snapshots, []


allocation_repository = AllocationRepository()
