"""Shared allocation reservation lock primitives (Phase 5A).

Centralises the single source of truth for port availability and order-scoped
reservation locks so billing, redemption, admin allocation management, and
server creation never drift on lock semantics or ordering.

Reservation states for an unassigned allocation (``server_id IS NULL``):
- **Free**: ``reserved_order_id IS NULL`` OR ``(reserved_until IS NOT NULL AND reserved_until <= now)``
- **Timed reservation (pending order)**: ``reserved_order_id = order.id`` AND ``reserved_until > now``
- **Strong reservation (paid/processing/manual_review/apply_failed)**: ``reserved_order_id = order.id`` AND ``reserved_until IS NULL``
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_naive_now_sec
from app.db.models.billing import BillingOrder
from app.db.models.pterodactyl import Allocation

# Extra TTL buffer beyond invoice.due_at to absorb last-second payment callback
# latency and the 1-minute order-close cron cadence.
RESERVATION_GRACE_MINUTES = 5

TERMINAL_ORDER_STATUSES: tuple[str, ...] = (
    "closed",
    "cancelled",
    "refunded",
    "applied",
)


class InsufficientAllocationsError(RuntimeError):
    """Raised when a node does not have enough free allocations to satisfy a lock."""

    def __init__(self, *, node_id: int, required: int, available: int) -> None:
        self.node_id = node_id
        self.required = required
        self.available = available
        super().__init__(
            f"节点 {node_id} 可用端口不足（需要 {required} 个，当前可用 {available} 个）"
        )


def _effective_now(now: datetime | None) -> datetime:
    return now if now is not None else utc_naive_now_sec()


def is_allocation_free_clause(now: datetime | None = None) -> ColumnElement[bool]:
    """SQL predicate matching allocations that can be freely assigned or reserved."""
    ts = _effective_now(now)
    return and_(
        Allocation.server_id.is_(None),
        or_(
            Allocation.reserved_order_id.is_(None),
            and_(
                Allocation.reserved_until.is_not(None),
                Allocation.reserved_until <= ts,
            ),
        ),
    )


def is_allocation_reserved_clause(now: datetime | None = None) -> ColumnElement[bool]:
    """SQL predicate matching allocations actively held by an order reservation."""
    ts = _effective_now(now)
    return and_(
        Allocation.server_id.is_(None),
        Allocation.reserved_order_id.is_not(None),
        or_(
            Allocation.reserved_until.is_(None),
            Allocation.reserved_until > ts,
        ),
    )


def is_allocation_actively_reserved(
    alloc: Allocation,
    now: datetime | None = None,
) -> bool:
    """In-memory equivalent of :func:`is_allocation_reserved_clause`."""
    if alloc.server_id is not None or alloc.reserved_order_id is None:
        return False
    if alloc.reserved_until is None:
        return True
    return alloc.reserved_until > _effective_now(now)


async def reserve_allocations_for_order(
    db: AsyncSession,
    *,
    node_id: int,
    order_id: int,
    count: int,
    reserved_until: datetime | None,
    now: datetime | None = None,
) -> list[int]:
    """Lock and reserve ``count`` free allocations on ``node_id`` for ``order_id``.

    Acquires rows in ``Allocation.id ASC`` order using ``FOR UPDATE SKIP LOCKED``.
    Raises :class:`InsufficientAllocationsError` without mutating any row if
    fewer than ``count`` free allocations are available.

    Returns the reserved allocation IDs in ascending ``id`` order. Caller owns
    the surrounding transaction (commit / rollback).
    """
    if count <= 0:
        return []

    ts = _effective_now(now)
    alloc_ids = list(
        (
            await db.scalars(
                select(Allocation.id)
                .where(
                    Allocation.node_id == node_id,
                    is_allocation_free_clause(ts),
                )
                .order_by(Allocation.id.asc())
                .limit(count)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    if len(alloc_ids) < count:
        raise InsufficientAllocationsError(
            node_id=node_id,
            required=count,
            available=len(alloc_ids),
        )

    await db.execute(
        update(Allocation)
        .where(Allocation.id.in_(alloc_ids))
        .values(
            reserved_order_id=order_id,
            reserved_until=reserved_until,
            updated_at=ts,
        )
    )
    return [int(aid) for aid in alloc_ids]


async def lock_and_ensure_order_allocations(
    db: AsyncSession,
    *,
    node_id: int,
    order_id: int,
    count: int,
    preferred_primary_id: int | None = None,
    now: datetime | None = None,
) -> tuple[int, list[int]]:
    """Lock all allocations reserved by ``order_id`` and top up any deficit.

    Used at delivery time (``_effect_new_purchase``):
    1. Locks existing unassigned reservations owned by ``order_id`` on ``node_id``
       in ``Allocation.id ASC`` order (``FOR UPDATE``).
    2. If fewer than ``count`` remain (e.g. a late payment arrived after TTL
       expiry and another order took a port), acquires the shortfall from free
       ports on the same node using ``FOR UPDATE SKIP LOCKED``. Raises
       :class:`InsufficientAllocationsError` if still short (existing locks stay
       intact for retry).
    3. Promotes all selected ports to strong reservations (``reserved_until=None``)
       and releases any surplus ports if more than ``count`` were held.

    Returns ``(primary_allocation_id, additional_allocation_ids)`` with
    ``additional_allocation_ids`` sorted ascending. Caller owns commit/rollback.
    """
    needed = max(1, int(count))
    ts = _effective_now(now)

    held_rows = list(
        (
            await db.scalars(
                select(Allocation)
                .where(
                    Allocation.node_id == node_id,
                    Allocation.reserved_order_id == order_id,
                    Allocation.server_id.is_(None),
                )
                .order_by(Allocation.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    held_ids = [int(row.id) for row in held_rows]

    extra_free_ids: list[int] = []
    if len(held_ids) < needed:
        deficit = needed - len(held_ids)
        free_stmt = (
            select(Allocation.id)
            .where(
                Allocation.node_id == node_id,
                is_allocation_free_clause(ts),
            )
            .order_by(Allocation.id.asc())
            .limit(deficit)
            .with_for_update(skip_locked=True)
        )
        if held_ids:
            free_stmt = free_stmt.where(Allocation.id.notin_(held_ids))
        extra_free_ids = [int(aid) for aid in (await db.scalars(free_stmt)).all()]
        if len(held_ids) + len(extra_free_ids) < needed:
            raise InsufficientAllocationsError(
                node_id=node_id,
                required=needed,
                available=len(held_ids) + len(extra_free_ids),
            )

    all_ids = sorted(held_ids + extra_free_ids)
    surplus_ids: list[int] = []
    if len(all_ids) > needed:
        if preferred_primary_id is not None and preferred_primary_id in all_ids:
            others = [aid for aid in all_ids if aid != preferred_primary_id]
            selected_ids = sorted([preferred_primary_id, *others[: needed - 1]])
        else:
            selected_ids = all_ids[:needed]
        selected_set = set(selected_ids)
        surplus_ids = [aid for aid in all_ids if aid not in selected_set]
    else:
        selected_ids = all_ids

    if surplus_ids:
        await db.execute(
            update(Allocation)
            .where(
                Allocation.id.in_(surplus_ids),
                Allocation.reserved_order_id == order_id,
                Allocation.server_id.is_(None),
            )
            .values(
                reserved_order_id=None,
                reserved_until=None,
                updated_at=ts,
            )
        )

    await db.execute(
        update(Allocation)
        .where(
            Allocation.id.in_(selected_ids),
            Allocation.server_id.is_(None),
        )
        .values(
            reserved_order_id=order_id,
            reserved_until=None,
            updated_at=ts,
        )
    )

    if preferred_primary_id is not None and preferred_primary_id in selected_ids:
        primary_id = preferred_primary_id
        extras = [aid for aid in selected_ids if aid != primary_id]
    else:
        primary_id = selected_ids[0]
        extras = selected_ids[1:]
    return primary_id, extras


async def promote_order_reservations(db: AsyncSession, order_id: int) -> int:
    """Upgrade timed reservations of ``order_id`` to strong locks (``reserved_until=NULL``).

    Idempotent. Returns the number of rows upgraded. Caller owns commit/rollback.
    """
    ts = utc_naive_now_sec()
    result = await db.execute(
        update(Allocation)
        .where(
            Allocation.reserved_order_id == order_id,
            Allocation.server_id.is_(None),
            Allocation.reserved_until.is_not(None),
        )
        .values(reserved_until=None, updated_at=ts)
    )
    return int(result.rowcount or 0) if isinstance(result, CursorResult) else 0


async def release_order_reservations(db: AsyncSession, order_id: int) -> int:
    """Release all unassigned allocations still reserved by ``order_id``.

    Safe against late-expiry takeover: rows already reclaimed by another order
    or bound to a real server are untouched. Returns released row count.
    """
    ts = utc_naive_now_sec()
    result = await db.execute(
        update(Allocation)
        .where(
            Allocation.reserved_order_id == order_id,
            Allocation.server_id.is_(None),
        )
        .values(
            reserved_order_id=None,
            reserved_until=None,
            updated_at=ts,
        )
    )
    return int(result.rowcount or 0) if isinstance(result, CursorResult) else 0


async def restore_order_strong_reservations(
    db: AsyncSession,
    order_id: int,
    allocation_ids: Sequence[int],
) -> int:
    """Re-acquire strong locks on ``allocation_ids`` after Wings create compensation.

    Locks candidate rows in ``Allocation.id ASC`` order and only restores rows
    that are currently unassigned and either unreserved or already held by
    ``order_id`` (never steals a port acquired by another order or server).
    Returns the number of restored rows.
    """
    sorted_ids = sorted({int(aid) for aid in allocation_ids})
    if not sorted_ids:
        return 0

    ts = utc_naive_now_sec()
    rows = list(
        (
            await db.scalars(
                select(Allocation)
                .where(Allocation.id.in_(sorted_ids))
                .order_by(Allocation.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    restorable_ids = [
        int(row.id)
        for row in rows
        if row.server_id is None
        and (row.reserved_order_id is None or row.reserved_order_id == order_id)
    ]
    if not restorable_ids:
        return 0

    result = await db.execute(
        update(Allocation)
        .where(
            Allocation.id.in_(restorable_ids),
            Allocation.server_id.is_(None),
        )
        .values(
            reserved_order_id=order_id,
            reserved_until=None,
            updated_at=ts,
        )
    )
    return int(result.rowcount or 0) if isinstance(result, CursorResult) else 0


async def reclaim_terminal_order_reservations(db: AsyncSession) -> int:
    """Release orphaned reservations tied to terminal orders (safety-net sweeper).

    Clears ``reserved_order_id`` / ``reserved_until`` on unassigned allocations
    pointing to orders in ``closed`` / ``cancelled`` / ``refunded`` / ``applied``.
    """
    ts = utc_naive_now_sec()
    terminal_order_ids = select(BillingOrder.id).where(
        BillingOrder.status.in_(TERMINAL_ORDER_STATUSES)
    )
    result = await db.execute(
        update(Allocation)
        .where(
            Allocation.server_id.is_(None),
            Allocation.reserved_order_id.is_not(None),
            Allocation.reserved_order_id.in_(terminal_order_ids),
        )
        .values(
            reserved_order_id=None,
            reserved_until=None,
            updated_at=ts,
        )
    )
    return int(result.rowcount or 0) if isinstance(result, CursorResult) else 0


async def has_active_reservations_on_node(
    db: AsyncSession,
    node_id: int,
    now: datetime | None = None,
) -> bool:
    """Return True if ``node_id`` has at least one actively reserved allocation."""
    ts = _effective_now(now)
    found = await db.scalar(
        select(Allocation.id)
        .where(
            Allocation.node_id == node_id,
            is_allocation_reserved_clause(ts),
        )
        .limit(1)
    )
    return found is not None
