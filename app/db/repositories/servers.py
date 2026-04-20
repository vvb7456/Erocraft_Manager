"""Server repository helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.manager import ServerMeta
from app.db.models.pterodactyl import EggVariable, PteroServer, ServerVariable


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
            .order_by(PteroServer.id.asc())
        )
        return list(result.scalars().all())

    async def list_for_owner(self, db: AsyncSession, owner_id: int) -> list[PteroServer]:
        result = await db.execute(
            select(PteroServer)
            .options(selectinload(PteroServer.meta))
            .where(PteroServer.owner_id == owner_id)
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
        """Return servers whose expiration_date < today and not yet suspended."""
        result = await db.execute(
            select(PteroServer)
            .join(ServerMeta, ServerMeta.server_id == PteroServer.id)
            .options(selectinload(PteroServer.meta))
            .where(ServerMeta.expiration_date < today, PteroServer.status.is_(None))
            .order_by(PteroServer.id.asc())
        )
        return list(result.scalars().all())

    async def list_expiring_on(self, db: AsyncSession, target_date: date) -> list[PteroServer]:
        result = await db.execute(
            select(PteroServer)
            .join(ServerMeta, ServerMeta.server_id == PteroServer.id)
            .options(selectinload(PteroServer.meta))
            .where(ServerMeta.expiration_date == target_date)
            .order_by(PteroServer.id.asc())
        )
        return list(result.scalars().all())

    async def list_expired_before_or_on(self, db: AsyncSession, threshold: date) -> list[PteroServer]:
        result = await db.execute(
            select(PteroServer)
            .join(ServerMeta, ServerMeta.server_id == PteroServer.id)
            .options(selectinload(PteroServer.meta))
            .where(ServerMeta.expiration_date <= threshold)
            .order_by(PteroServer.id.asc())
        )
        return list(result.scalars().all())


server_repository = ServerRepository()
