"""Server repository helpers."""

from __future__ import annotations

from datetime import date

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.manager import ServerMeta
from app.db.models.pterodactyl import EggVariable, PteroServer, ServerVariable


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
    ) -> bool:
        """Update a single startup variable value. Returns True if successful."""
        result = await db.execute(
            select(EggVariable).where(
                EggVariable.egg_id == egg_id,
                EggVariable.env_variable == env_variable,
                EggVariable.user_editable == 1,
            )
        )
        egg_var = result.scalar_one_or_none()
        if egg_var is None:
            return False

        sv_result = await db.execute(
            select(ServerVariable).where(
                ServerVariable.server_id == server_id,
                ServerVariable.variable_id == egg_var.id,
            )
        )
        sv = sv_result.scalar_one_or_none()
        if sv is not None:
            sv.variable_value = value
        else:
            db.add(ServerVariable(
                server_id=server_id,
                variable_id=egg_var.id,
                variable_value=value,
            ))
        return True

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
