"""Server repository helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.manager import ServerMeta
from app.db.models.pterodactyl import EggVariable, PteroServer, ServerVariable


# Billing 占位服务器行用 ``external_id LIKE 'pending:%'`` 标识 (docs/BILLING_DESIGN.md §6).
# 所有面向"用户/admin 可见服务器"的 list 查询都需要排除这些占位行。资源统计
# (dashboard) 不过滤，因为占位仍在物理上预占 CPU/内存/磁盘配额 (§13.5)。
_PLACEHOLDER_PATTERN = "pending:%"


def exclude_placeholders():
    """SQL clause excluding billing placeholder rows (`external_id LIKE 'pending:%'`).

    Use in any WHERE clause that loads "real" servers. See BILLING_DESIGN.md §13.5.
    """
    return or_(
        PteroServer.external_id.is_(None),
        PteroServer.external_id.notlike(_PLACEHOLDER_PATTERN),
    )


# Legacy alias kept for internal callers in this module.
_exclude_placeholders = exclude_placeholders


@dataclass(slots=True)
class StartupVariableUpdateResult:
    variable: EggVariable
    old_value: str
    new_value: str

    @property
    def changed(self) -> bool:
        return self.old_value != self.new_value


class ServerRepository:
    async def get_by_id(self, db: AsyncSession, server_id: int) -> PteroServer | None:
        result = await db.execute(
            select(PteroServer)
            .options(selectinload(PteroServer.meta))
            .where(PteroServer.id == server_id)
        )
        return result.scalar_one_or_none()

    async def list_all_for_dashboard(self, db: AsyncSession) -> list[PteroServer]:
        result = await db.execute(select(PteroServer).options(selectinload(PteroServer.meta)))
        return list(result.scalars().all())

    async def list_for_admin(self, db: AsyncSession) -> list[PteroServer]:
        result = await db.execute(
            select(PteroServer)
            .options(selectinload(PteroServer.meta))
            .where(_exclude_placeholders())
            .order_by(PteroServer.id.asc())
        )
        return list(result.scalars().all())

    async def list_for_owner(self, db: AsyncSession, owner_id: int) -> list[PteroServer]:
        result = await db.execute(
            select(PteroServer)
            .options(selectinload(PteroServer.meta))
            .where(PteroServer.owner_id == owner_id, _exclude_placeholders())
            .order_by(PteroServer.created_at.desc(), PteroServer.id.desc())
        )
        return list(result.scalars().all())

    async def list_startup_variables(
        self,
        db: AsyncSession,
        *,
        server_id: int,
        egg_id: int,
    ) -> list[tuple[EggVariable, str | None]]:
        result = await db.execute(
            select(EggVariable, ServerVariable.variable_value)
            .outerjoin(
                ServerVariable,
                and_(
                    ServerVariable.variable_id == EggVariable.id,
                    ServerVariable.server_id == server_id,
                ),
            )
            .where(EggVariable.egg_id == egg_id)
            .order_by(EggVariable.id.asc())
        )
        return [(variable, value) for variable, value in result.all()]

    async def update_startup_variable(
        self,
        db: AsyncSession,
        *,
        server_id: int,
        egg_id: int,
        env_variable: str,
        value: str,
    ) -> StartupVariableUpdateResult | None:
        """Update a single startup variable value and return Panel-style change data."""
        result = await db.execute(
            select(EggVariable).where(
                EggVariable.egg_id == egg_id,
                EggVariable.env_variable == env_variable,
                EggVariable.user_editable == 1,
            )
        )
        egg_var = result.scalar_one_or_none()
        if egg_var is None:
            return None

        sv_result = await db.execute(
            select(ServerVariable).where(
                ServerVariable.server_id == server_id,
                ServerVariable.variable_id == egg_var.id,
            )
        )
        sv = sv_result.scalar_one_or_none()
        old_value = sv.variable_value if sv is not None and sv.variable_value is not None else egg_var.default_value
        new_value = value or ""
        if sv is not None:
            sv.variable_value = new_value
        else:
            db.add(ServerVariable(
                server_id=server_id,
                variable_id=egg_var.id,
                variable_value=new_value,
            ))
        return StartupVariableUpdateResult(
            variable=egg_var,
            old_value=old_value,
            new_value=new_value,
        )

    async def list_suspend_candidates(self, db: AsyncSession, today: date) -> list[PteroServer]:
        """Return servers whose expiration_date < today and not yet suspended.

        Trial servers are excluded — they bypass the global suspend cadence
        and are deleted with zero grace by the dedicated trial_expire task.
        """
        result = await db.execute(
            select(PteroServer)
            .join(ServerMeta, ServerMeta.server_id == PteroServer.id)
            .options(selectinload(PteroServer.meta))
            .where(
                ServerMeta.expiration_date < today,
                PteroServer.status.is_(None),
                ServerMeta.is_trial.is_(False),
                _exclude_placeholders(),
            )
            .order_by(PteroServer.id.asc())
        )
        return list(result.scalars().all())

    async def list_expiring_on(self, db: AsyncSession, target_date: date) -> list[PteroServer]:
        result = await db.execute(
            select(PteroServer)
            .join(ServerMeta, ServerMeta.server_id == PteroServer.id)
            .options(selectinload(PteroServer.meta))
            .where(ServerMeta.expiration_date == target_date, _exclude_placeholders())
            .order_by(PteroServer.id.asc())
        )
        return list(result.scalars().all())

    async def list_expired_before_or_on(self, db: AsyncSession, threshold: date) -> list[PteroServer]:
        """Return non-trial servers expired at or before ``threshold``.

        Trial servers are excluded — they follow their own zero-grace
        deletion via :meth:`list_trial_expired`.
        """
        result = await db.execute(
            select(PteroServer)
            .join(ServerMeta, ServerMeta.server_id == PteroServer.id)
            .options(selectinload(PteroServer.meta))
            .where(
                ServerMeta.expiration_date <= threshold,
                ServerMeta.is_trial.is_(False),
                _exclude_placeholders(),
            )
            .order_by(PteroServer.id.asc())
        )
        return list(result.scalars().all())

    async def list_trial_expired(self, db: AsyncSession, today: date) -> list[PteroServer]:
        """Return trial servers whose expiration_date < today.

        These are deleted with zero grace (no suspend step, no
        AUTOMATION_DELETE_DAYS window) by the trial_expire task.
        """
        result = await db.execute(
            select(PteroServer)
            .join(ServerMeta, ServerMeta.server_id == PteroServer.id)
            .options(selectinload(PteroServer.meta))
            .where(
                ServerMeta.expiration_date < today,
                ServerMeta.is_trial.is_(True),
                _exclude_placeholders(),
            )
            .order_by(PteroServer.id.asc())
        )
        return list(result.scalars().all())


server_repository = ServerRepository()
