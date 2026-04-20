"""Manager activity log repository helpers."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ManagerActivityLog


class ActivityLogRepository:
    async def list_manager_logs(
        self,
        db: AsyncSession,
        *,
        page: int,
        per_page: int,
        actor: str | None = None,
        action: str | None = None,
        status: str | None = None,
    ) -> tuple[list[ManagerActivityLog], int]:
        filters = []
        if actor:
            filters.append(ManagerActivityLog.actor == actor)
        if action:
            filters.append(ManagerActivityLog.action == action)
        if status:
            filters.append(ManagerActivityLog.status == status)

        query = select(ManagerActivityLog)
        count_query = select(func.count(ManagerActivityLog.id))
        if filters:
            query = query.where(*filters)
            count_query = count_query.where(*filters)

        query = query.order_by(ManagerActivityLog.timestamp.desc()).offset((page - 1) * per_page).limit(per_page)
        rows = await db.execute(query)
        total = await db.execute(count_query)
        return list(rows.scalars().all()), int(total.scalar_one() or 0)

    async def distinct_actors(self, db: AsyncSession) -> list[str]:
        rows = await db.execute(
            select(ManagerActivityLog.actor)
            .distinct()
            .where(ManagerActivityLog.actor != "")
            .order_by(ManagerActivityLog.actor.asc())
        )
        return [str(value) for value in rows.scalars().all()]

    async def distinct_actions(self, db: AsyncSession) -> list[str]:
        rows = await db.execute(
            select(ManagerActivityLog.action)
            .distinct()
            .where(ManagerActivityLog.action != "")
            .order_by(ManagerActivityLog.action.asc())
        )
        return [str(value) for value in rows.scalars().all()]


activity_log_repository = ActivityLogRepository()
