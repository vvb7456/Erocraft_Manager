"""Direct panel DB writes — replaces Pterodactyl Application API.

All operations write the panel MySQL tables directly. They produce data that
is bit-for-bit equivalent to what the Pterodactyl Panel itself would write,
but without triggering panel business-layer side-effects (no AccountCreated
notification, no activity log entries, etc.).

Background and design rationale: see docs/PTERO_API_DECOUPLING.md.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PteroServer, PteroUser
from app.db.models.pterodactyl import (
    Allocation,
    Egg,
    EggVariable,
    PanelNode,
    ServerVariable,
)

logger = logging.getLogger(__name__)


class PanelDBError(RuntimeError):
    """Raised when a direct panel-DB write fails or violates a precondition."""


class PanelDBValidationError(PanelDBError):
    """Raised when input validation rejects a request before any DB write.

    Distinguishing this from generic ``PanelDBError`` lets routers map
    user-correctable input errors to HTTP 422 instead of 502.
    """


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _now() -> datetime:
    # Pterodactyl stores naive UTC datetimes
    return datetime.utcnow().replace(microsecond=0)


def _new_uuid() -> str:
    return str(_uuid.uuid4())


def _short_uuid(full_uuid: str) -> str:
    """Pterodactyl uses the first 8 hex chars of the full UUID as uuidShort."""
    return full_uuid.replace("-", "")[:8]


# ---------------------------------------------------------------------------
# User operations
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class CreatedUser:
    id: int
    uuid: str
    username: str
    email: str


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    email: str,
    first_name: str,
    last_name: str,
    password: str,
    root_admin: bool = False,
    language: str = "zh",
) -> CreatedUser:
    """Insert a new panel user. Caller is responsible for db.commit()."""
    user = PteroUser(
        uuid=_new_uuid(),
        username=username,
        email=email,
        name_first=first_name,
        name_last=last_name,
        language=language,
        root_admin=root_admin,
        use_totp=False,
        gravatar=True,
        created_at=_now(),
        updated_at=_now(),
    )
    user.password = await asyncio.to_thread(PteroUser.hash_password_sync, password)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise PanelDBError(f"用户创建失败（用户名或邮箱冲突）: {exc.orig}") from exc
    return CreatedUser(id=int(user.id), uuid=user.uuid, username=user.username, email=user.email)


async def create_user_with_hashed_password(
    db: AsyncSession,
    *,
    username: str,
    email: str,
    first_name: str,
    last_name: str,
    password_hash: str,
    root_admin: bool = False,
    language: str = "zh",
) -> CreatedUser:
    """Insert a panel user using a pre-computed bcrypt ``$2y$`` hash.

    Used by the public-registration verification flow where the password was
    captured (and hashed) at sign-up time and we don't want to keep the plain
    text around until the user clicks the verification link.
    """
    user = PteroUser(
        uuid=_new_uuid(),
        username=username,
        email=email,
        name_first=first_name,
        name_last=last_name,
        language=language,
        root_admin=root_admin,
        use_totp=False,
        gravatar=True,
        created_at=_now(),
        updated_at=_now(),
    )
    user.password = password_hash
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise PanelDBError(f"用户创建失败（用户名或邮箱冲突）: {exc.orig}") from exc
    return CreatedUser(id=int(user.id), uuid=user.uuid, username=user.username, email=user.email)


async def update_user(
    db: AsyncSession,
    user_id: int,
    *,
    email: str,
    username: str,
    first_name: str,
    last_name: str,
    password: str | None = None,
    language: str | None = None,
) -> None:
    """Update an existing user. Caller is responsible for db.commit()."""
    user = await db.get(PteroUser, user_id)
    if user is None:
        raise PanelDBError(f"用户 {user_id} 不存在")
    user.email = email
    user.username = username
    user.name_first = first_name
    user.name_last = last_name
    if password:
        user.password = await asyncio.to_thread(PteroUser.hash_password_sync, password)
    if language is not None:
        user.language = language
    user.updated_at = _now()
    try:
        await db.flush()
    except IntegrityError as exc:
        raise PanelDBError(f"用户更新失败（用户名或邮箱冲突）: {exc.orig}") from exc


async def delete_user(db: AsyncSession, user_id: int) -> None:
    """Delete a user. Servers MUST be deleted first (FK constraint).

    Caller is responsible for db.commit(). Idempotent: missing user is OK.
    """
    user = await db.get(PteroUser, user_id)
    if user is None:
        return
    await db.delete(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise PanelDBError(
            f"删除用户 {user_id} 失败（请先删除其名下服务器）: {exc.orig}"
        ) from exc


# ---------------------------------------------------------------------------
# Server operations
# ---------------------------------------------------------------------------


async def find_available_allocation(
    db: AsyncSession,
    node_id: int,
    *,
    lock: bool = True,
) -> int | None:
    """Pick the lowest-id unassigned allocation on a node.

    Used by billing order placement (docs/BILLING_DESIGN.md §6) to grab a
    free port concurrently across racing orders. Combines ``ORDER BY id ASC``
    + ``FOR UPDATE SKIP LOCKED`` so two orders on the same node see different
    rows. Caller must hold a transaction; binds the chosen allocation to a
    server before COMMIT to convert the lock into a permanent assignment.

    Returns ``None`` when the node has no free allocations left.
    """
    stmt = (
        select(Allocation.id)
        .where(Allocation.node_id == node_id, Allocation.server_id.is_(None))
        .order_by(Allocation.id.asc())
        .limit(1)
    )
    if lock:
        stmt = stmt.with_for_update(skip_locked=True)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


@dataclass(slots=True, frozen=True)
class CreatedServer:
    id: int
    uuid: str
    uuid_short: str
    name: str
    owner_id: int
    node_id: int
    allocation_id: int


async def create_server(
    db: AsyncSession,
    *,
    owner_id: int,
    node_id: int,
    allocation_id: int,
    egg_id: int,
    nest_id: int,
    name: str,
    description: str = "",
    memory: int,
    swap: int = 0,
    disk: int,
    io: int = 500,
    cpu: int,
    image: str,
    startup: str,
    environment: dict[str, str],
    database_limit: int = 0,
    backup_limit: int = 0,
    allocation_limit: int | None = None,
    skip_scripts: bool = False,
    oom_disabled: bool = True,
    threads: str | None = None,
    external_id: str | None = None,
    allocation_additional: list[int] | None = None,
) -> CreatedServer:
    """Insert a server with its variables and bind the allocation(s).

    Mirrors Pterodactyl's ``ServerCreationService``:

    - Validates that the primary allocation belongs to ``node_id`` and is
      unassigned (and same for every entry in ``allocation_additional``).
    - Runs every egg variable's ``rules`` through
      :mod:`app.services.egg_validator`.
    - Sets ``status='installing'`` so Wings will run the install pipeline
      when notified via ``WingsService.create_server``.
    - Defaults ``oom_disabled`` to ``True`` to match Panel's
      ``ServerCreationService::createModel``.

    The ``environment`` dict maps env_variable name → value; missing
    variables are filled from ``egg_variables.default_value``.

    Caller is responsible for ``db.commit()``.
    """
    from app.services.egg_validator import EggValidationError, validate_environment

    # Validate referenced rows exist (owner / node / egg / nest) up-front so
    # we return semantic errors instead of raw FK IntegrityError → 502.
    if await db.get(PteroUser, owner_id) is None:
        raise PanelDBValidationError(f"用户 {owner_id} 不存在")
    if await db.get(PanelNode, node_id) is None:
        raise PanelDBValidationError(f"节点 {node_id} 不存在")
    egg = await db.get(Egg, egg_id)
    if egg is None:
        raise PanelDBValidationError(f"Egg {egg_id} 不存在")
    if int(egg.nest_id) != int(nest_id):
        raise PanelDBValidationError(
            f"Egg {egg_id} 实际归属 nest {egg.nest_id}，与传入的 nest_id={nest_id} 不一致"
        )

    # Validate primary allocation
    alloc = await db.get(Allocation, allocation_id)
    if alloc is None:
        raise PanelDBValidationError(f"分配 {allocation_id} 不存在")
    if alloc.node_id != node_id:
        raise PanelDBValidationError(
            f"分配 {allocation_id} 不在节点 {node_id} 上（实际节点 {alloc.node_id}）"
        )
    if alloc.server_id is not None:
        raise PanelDBValidationError(f"分配 {allocation_id} 已被服务器 {alloc.server_id} 占用")

    # Validate additional allocations
    additional_allocs: list[Allocation] = []
    if allocation_additional:
        for extra_id in allocation_additional:
            extra = await db.get(Allocation, extra_id)
            if extra is None:
                raise PanelDBValidationError(f"附加分配 {extra_id} 不存在")
            if extra.node_id != node_id:
                raise PanelDBValidationError(
                    f"附加分配 {extra_id} 不在节点 {node_id} 上（实际节点 {extra.node_id}）"
                )
            if extra.server_id is not None:
                raise PanelDBValidationError(
                    f"附加分配 {extra_id} 已被服务器 {extra.server_id} 占用"
                )
            additional_allocs.append(extra)

    # Pre-fetch egg variables once and validate environment values against rules
    egg_var_rows = await db.execute(
        select(EggVariable).where(EggVariable.egg_id == egg_id)
    )
    egg_vars = list(egg_var_rows.scalars().all())
    for ev in egg_vars:
        value = environment.get(ev.env_variable, ev.default_value)
        try:
            validate_environment(ev.env_variable, value, ev.rules)
        except EggValidationError as exc:
            raise PanelDBValidationError(str(exc)) from exc

    server_uuid = _new_uuid()
    server = PteroServer(
        external_id=external_id,
        uuid=server_uuid,
        uuid_short=_short_uuid(server_uuid),
        node_id=node_id,
        name=name,
        description=description or "",
        status="installing",
        skip_scripts=skip_scripts,
        owner_id=owner_id,
        memory=int(memory),
        swap=int(swap),
        disk=int(disk),
        io=int(io),
        cpu=int(cpu),
        threads=threads,
        oom_disabled=bool(oom_disabled),
        allocation_id=int(allocation_id),
        nest_id=int(nest_id),
        egg_id=int(egg_id),
        startup=startup,
        image=image,
        allocation_limit=allocation_limit,
        database_limit=int(database_limit),
        backup_limit=int(backup_limit),
        created_at=_now(),
        updated_at=_now(),
        installed_at=None,
    )
    db.add(server)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise PanelDBError(f"创建服务器失败: {exc.orig}") from exc

    server_id = int(server.id)

    # Bind primary + additional allocations to the new server
    alloc.server_id = server_id
    alloc.updated_at = _now()
    for extra in additional_allocs:
        extra.server_id = server_id
        extra.updated_at = _now()

    # Insert all server_variables (one per egg_variable). Missing → default.
    for ev in egg_vars:
        value = environment.get(ev.env_variable, ev.default_value)
        if value is None:
            value = ev.default_value
        db.add(
            ServerVariable(
                server_id=server_id,
                variable_id=int(ev.id),
                variable_value=str(value),
                created_at=_now(),
                updated_at=_now(),
            )
        )

    await db.flush()
    return CreatedServer(
        id=server_id,
        uuid=server.uuid,
        uuid_short=server.uuid_short,
        name=server.name,
        owner_id=int(server.owner_id),
        node_id=int(server.node_id),
        allocation_id=int(server.allocation_id),
    )


async def set_server_status(
    db: AsyncSession,
    server_id: int,
    status_value: str | None,
) -> None:
    """Update servers.status. Use 'suspended' / 'installing' / None (=normal).

    Caller is responsible for db.commit().
    """
    result = await db.execute(
        update(PteroServer)
        .where(PteroServer.id == server_id)
        .values(status=status_value, updated_at=_now())
    )
    if result.rowcount == 0:
        raise PanelDBError(f"服务器 {server_id} 不存在")


async def mark_for_reinstall(db: AsyncSession, server_id: int) -> None:
    """Reset state to 'installing' + clear installed_at. Wings will rerun script."""
    result = await db.execute(
        update(PteroServer)
        .where(PteroServer.id == server_id)
        .values(status="installing", installed_at=None, updated_at=_now())
    )
    if result.rowcount == 0:
        raise PanelDBError(f"服务器 {server_id} 不存在")


async def update_server_limits(
    db: AsyncSession,
    server_id: int,
    *,
    memory: int | None = None,
    swap: int | None = None,
    disk: int | None = None,
    io: int | None = None,
    cpu: int | None = None,
    allocation_limit: int | None = None,
    database_limit: int | None = None,
    backup_limit: int | None = None,
    threads: str | None = None,
    update_threads: bool = False,
    oom_disabled: bool | None = None,
) -> None:
    """Update build limits. Pair with ``WingsService.sync_server`` afterward."""
    fields: dict[str, object] = {"updated_at": _now()}
    if memory is not None:
        fields["memory"] = int(memory)
    if swap is not None:
        fields["swap"] = int(swap)
    if disk is not None:
        fields["disk"] = int(disk)
    if io is not None:
        fields["io"] = int(io)
    if cpu is not None:
        fields["cpu"] = int(cpu)
    if allocation_limit is not None:
        fields["allocation_limit"] = int(allocation_limit)
    if database_limit is not None:
        fields["database_limit"] = int(database_limit)
    if backup_limit is not None:
        fields["backup_limit"] = int(backup_limit)
    if update_threads:
        fields["threads"] = threads if threads else None
    if oom_disabled is not None:
        fields["oom_disabled"] = bool(oom_disabled)

    result = await db.execute(
        update(PteroServer).where(PteroServer.id == server_id).values(**fields)
    )
    if result.rowcount == 0:
        raise PanelDBError(f"服务器 {server_id} 不存在")


_EXPIRATION_LINE_RE = re.compile(
    r"(^|\n)到期时间[：:]\s*\d{4}[/-]\d{1,2}[/-]\d{1,2}(?=\n|$)"
)
# 占位阶段写入的「订单 EMxxxx…」行，apply 成功后一并清理。
_ORDER_PLACEHOLDER_LINE_RE = re.compile(
    r"(^|\n)订单\s+EM[A-Z0-9]+(?=\n|$)"
)


async def sync_server_expiration_description(
    db: AsyncSession,
    server_id: int,
    expiration_iso: str | None,
) -> None:
    """Replace any existing 到期时间 line in description with the new one.

    ``expiration_iso`` should be in ``YYYY/MM/DD`` format already (see existing
    callers). Pass ``None`` to remove the line.
    """
    server = await db.get(PteroServer, server_id)
    if server is None:
        raise PanelDBError(f"服务器 {server_id} 不存在")
    old_desc = server.description or ""
    cleaned = _EXPIRATION_LINE_RE.sub("", old_desc)
    cleaned = _ORDER_PLACEHOLDER_LINE_RE.sub("", cleaned).strip()
    if expiration_iso is None:
        new_desc = cleaned
    else:
        line = f"到期时间：{expiration_iso}"
        new_desc = f"{line}\n{cleaned}".strip() if cleaned else line
    server.description = new_desc
    server.updated_at = _now()


async def delete_server_row(db: AsyncSession, server_id: int) -> None:
    """Delete the server row.

    Mirrors Pterodactyl's ``ServerDeletionService``:

    1. UPDATE allocations SET notes=NULL WHERE server_id=X (panel always
       clears the friendly name before unbinding).
    2. ``allocations.server_id`` FK is ``ON DELETE SET NULL`` → ports are
       auto-released by the FK trigger when the server row is deleted.
    3. ``server_variables``, ``manager_server_meta`` and similar tables
       have ``ON DELETE CASCADE``; the database removes them itself.

    Uses a raw DELETE so we delegate child cleanup to the database — the
    ORM doesn't know about every child table (e.g. manager_server_meta has
    a composite PK that SQLAlchemy refuses to NULL out).

    NOTE: this function only handles server_id and allocations. Wings
    container destruction, backup-archive cleanup and remote MySQL DROPs
    are orchestrated by :mod:`app.services.server_lifecycle.delete_server`
    BEFORE this function is called.

    Idempotent. Caller is responsible for db.commit().
    """
    from sqlalchemy import delete as sql_delete
    from sqlalchemy import update as sql_update

    # Mirror panel: clear friendly notes on every allocation before unbinding
    await db.execute(
        sql_update(Allocation)
        .where(Allocation.server_id == server_id)
        .values(notes=None, updated_at=_now())
    )
    await db.execute(sql_delete(PteroServer).where(PteroServer.id == server_id))
    await db.flush()


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


async def get_server_uuid_and_node(
    db: AsyncSession, server_id: int
) -> tuple[str, int]:
    """Return (uuid, node_id) — used by lifecycle layer to address Wings."""
    row = await db.execute(
        select(PteroServer.uuid, PteroServer.node_id).where(PteroServer.id == server_id)
    )
    result = row.first()
    if result is None:
        raise PanelDBError(f"服务器 {server_id} 不存在")
    return str(result[0]), int(result[1])
