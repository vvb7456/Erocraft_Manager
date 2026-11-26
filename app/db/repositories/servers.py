"""Read-only server repository helpers."""

from __future__ import annotations

from datetime import date

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pterodactyl import EggVariable, PteroServer, ServerVariable


class ServerRepository:
    async def get_by_id(self, db: AsyncSession, server_id: int) -> PteroServer | None:
        result = await db.execute(
            select(PteroServer).where(PteroServer.id == server_id)
        )
        return result.scalar_one_or_none()

    async def list_all_for_dashboard(self, db: AsyncSession) -> list[PteroServer]:
        result = await db.execute(select(PteroServer))
        return list(result.scalars().all())

    async def list_for_admin(self, db: AsyncSession) -> list[PteroServer]:
        result = await db.execute(
            select(PteroServer).order_by(PteroServer.id.asc())
        )
        return list(result.scalars().all())

    async def list_for_owner(self, db: AsyncSession, owner_id: int) -> list[PteroServer]:
        result = await db.execute(
            select(PteroServer)
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

    async def list_suspend_candidates(self, db: AsyncSession, today: date) -> list[PteroServer]:
        """Return servers whose expiration_date < today and not yet suspended.

        Trial servers are excluded — they bypass the global suspend cadence
        and are deleted with zero grace by the dedicated trial_expire task.
        """
        result = await db.execute(
            select(PteroServer)
            .where(
                PteroServer.expiration_date < today,
                PteroServer.status.is_(None),
                PteroServer.is_trial.is_(False),
            )
            .order_by(PteroServer.id.asc())
        )
        return list(result.scalars().all())

    async def list_expiring_on(self, db: AsyncSession, target_date: date) -> list[PteroServer]:
        result = await db.execute(
            select(PteroServer)
            .where(PteroServer.expiration_date == target_date)
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
            .where(
                PteroServer.expiration_date <= threshold,
                PteroServer.is_trial.is_(False),
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
            .where(
                PteroServer.expiration_date < today,
                PteroServer.is_trial.is_(True),
            )
            .order_by(PteroServer.id.asc())
        )
        return list(result.scalars().all())


server_repository = ServerRepository()
