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
from typing import Any, Iterable

from sqlalchemy import String, and_, cast, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, joinedload

from app.core.time import utc_naive_now_sec
from app.db.models.billing import BillingOrder
from app.db.models.pterodactyl import Allocation, PteroServer, PteroUser
from app.db.repositories.allocation_reservations import (
    is_allocation_actively_reserved,
    is_allocation_free_clause,
    is_allocation_reserved_clause,
)
from app.db.sorting import SortSpec, build_order_by


_ALLOCATION_SORT_COLUMNS: dict[str, Any] = {
    "ip": SortSpec(Allocation.ip, tie_breakers=(Allocation.port, Allocation.id)),
    "port": SortSpec(Allocation.port, tie_breakers=(Allocation.ip, Allocation.id)),
    "alias": SortSpec(Allocation.ip_alias, nulls_last=True, empty_as_null=True),
    "server": SortSpec(PteroServer.name, nulls_last=True),
}


class AllocationRepository:
    # ----- read -----

    async def list_all(
        self,
        db: AsyncSession,
        node_id: int,
        *,
        assigned: bool | None = None,
        reserved: bool | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str | None = None,
        sort_order: str = "asc",
        now: datetime | None = None,
    ) -> tuple[list[tuple[Allocation, str | None]], int]:
        """Return ``([(allocation, reserved_order_no), ...], total)``.

        ``search`` matches against port (numeric prefix), ip, ip_alias,
        notes, server name, server uuid_short — case-insensitive.
        Uses an integer LEFT JOIN on ``Allocation.reserved_order_id == BillingOrder.id``
        to load ``order_no`` safely regardless of table collation differences.
        """
        ts = now if now is not None else utc_naive_now_sec()
        need_server_join = bool(search) or sort_by == "server"
        stmt = (
            select(Allocation, BillingOrder.order_no)
            .outerjoin(BillingOrder, Allocation.reserved_order_id == BillingOrder.id)
            .where(Allocation.node_id == node_id)
        )
        if need_server_join:
            stmt = stmt.outerjoin(
                PteroServer, Allocation.server_id == PteroServer.id
            ).options(contains_eager(Allocation.server))
        else:
            stmt = stmt.options(joinedload(Allocation.server))

        count_stmt = select(func.count()).select_from(Allocation).where(
            Allocation.node_id == node_id
        )

        if assigned is True:
            stmt = stmt.where(Allocation.server_id.isnot(None))
            count_stmt = count_stmt.where(Allocation.server_id.isnot(None))
        elif assigned is False:
            stmt = stmt.where(Allocation.server_id.is_(None))
            count_stmt = count_stmt.where(Allocation.server_id.is_(None))

        if reserved is True:
            reserved_cond = is_allocation_reserved_clause(ts)
            stmt = stmt.where(reserved_cond)
            count_stmt = count_stmt.where(reserved_cond)
        elif reserved is False:
            not_reserved_cond = ~is_allocation_reserved_clause(ts)
            stmt = stmt.where(not_reserved_cond)
            count_stmt = count_stmt.where(not_reserved_cond)

        if search:
            needle = f"%{search.strip()}%"
            search_cond = or_(
                Allocation.ip.ilike(needle),
                Allocation.ip_alias.ilike(needle),
                Allocation.notes.ilike(needle),
                cast(Allocation.port, String).ilike(needle),
                PteroServer.name.ilike(needle),
                PteroServer.uuid_short.ilike(needle),
                and_(is_allocation_reserved_clause(ts), BillingOrder.order_no.ilike(needle)),
            )
            stmt = stmt.where(search_cond)
            count_stmt = (
                select(func.count(func.distinct(Allocation.id)))
                .select_from(Allocation)
                .outerjoin(PteroServer, Allocation.server_id == PteroServer.id)
                .outerjoin(BillingOrder, Allocation.reserved_order_id == BillingOrder.id)
                .where(Allocation.node_id == node_id, search_cond)
            )
            if assigned is True:
                count_stmt = count_stmt.where(Allocation.server_id.isnot(None))
            elif assigned is False:
                count_stmt = count_stmt.where(Allocation.server_id.is_(None))
            if reserved is True:
                count_stmt = count_stmt.where(is_allocation_reserved_clause(ts))
            elif reserved is False:
                count_stmt = count_stmt.where(~is_allocation_reserved_clause(ts))

        order_clauses = build_order_by(
            sort_by,
            sort_order,
            _ALLOCATION_SORT_COLUMNS,
            default=(Allocation.ip.asc(), Allocation.port.asc(), Allocation.id.asc()),
            tie_breakers=(Allocation.ip, Allocation.port, Allocation.id),
        )
        stmt = stmt.order_by(*order_clauses).limit(limit).offset(offset)

        rows = (await db.execute(stmt)).unique().all()
        total = (await db.execute(count_stmt)).scalar_one()
        return [(row[0], row[1]) for row in rows], int(total)

    async def summary(
        self, db: AsyncSession, node_id: int, *, now: datetime | None = None
    ) -> tuple[int, int, int]:
        """Return ``(assigned, reserved, free)`` counts for the node."""
        ts = now if now is not None else utc_naive_now_sec()
        assigned = (
            await db.execute(
                select(func.count()).select_from(Allocation).where(
                    Allocation.node_id == node_id, Allocation.server_id.isnot(None)
                )
            )
        ).scalar_one()
        reserved = (
            await db.execute(
                select(func.count()).select_from(Allocation).where(
                    Allocation.node_id == node_id, is_allocation_reserved_clause(ts)
                )
            )
        ).scalar_one()
        free = (
            await db.execute(
                select(func.count()).select_from(Allocation).where(
                    Allocation.node_id == node_id, is_allocation_free_clause(ts)
                )
            )
        ).scalar_one()
        return int(assigned), int(reserved), int(free)

    async def get_order_nos(
        self, db: AsyncSession, order_ids: Iterable[int]
    ) -> dict[int, str]:
        ids = sorted({int(i) for i in order_ids if i})
        if not ids:
            return {}
        rows = (
            await db.execute(
                select(BillingOrder.id, BillingOrder.order_no).where(
                    BillingOrder.id.in_(ids)
                )
            )
        ).all()
        return {int(r[0]): str(r[1]) for r in rows}

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

        now = utc_naive_now_sec()
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
        ``"not_found"`` / ``"in_use"`` / ``"reserved"`` / ``None``."""
        row = (
            await db.execute(
                select(Allocation)
                .where(Allocation.id == allocation_id, Allocation.node_id == node_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return None, "not_found"
        if row.server_id is not None:
            return row, "in_use"
        if is_allocation_actively_reserved(row):
            return row, "reserved"
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
        """Returns ``(deleted, conflicting)``. If any conflict (wrong node,
        in-use, or actively reserved), no rows are deleted — caller must roll
        back the surrounding transaction."""
        sorted_ids = sorted({int(i) for i in ids})
        if not sorted_ids:
            return [], []
        ts = utc_naive_now_sec()
        rows = list(
            (
                await db.execute(
                    select(Allocation)
                    .where(Allocation.id.in_(sorted_ids))
                    .order_by(Allocation.id.asc())
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalars().all()
        )

        seen_ids = {r.id for r in rows}
        missing = [i for i in sorted_ids if i not in seen_ids]
        conflicting = [
            r
            for r in rows
            if r.node_id != node_id
            or r.server_id is not None
            or is_allocation_actively_reserved(r, ts)
        ]

        if missing or conflicting:
            return [], conflicting

        snapshots = [
            Allocation(id=r.id, node_id=r.node_id, ip=r.ip, port=r.port,
                       ip_alias=r.ip_alias, server_id=None, notes=r.notes)
            for r in rows
        ]
        await db.execute(delete(Allocation).where(Allocation.id.in_(sorted_ids)))
        await db.flush()
        return snapshots, []


allocation_repository = AllocationRepository()
