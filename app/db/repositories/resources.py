"""Repository helpers for admin resources and create-server defaults."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pterodactyl import Allocation, Egg, EggVariable, Nest, PanelNode, PteroUser


class ResourceRepository:
    async def list_users_simple(self, db: AsyncSession) -> list[PteroUser]:
        result = await db.execute(select(PteroUser).order_by(PteroUser.username.asc()))
        return list(result.scalars().all())

    async def list_nests(self, db: AsyncSession) -> list[Nest]:
        result = await db.execute(select(Nest).order_by(Nest.name.asc()))
        return list(result.scalars().all())

    async def list_nodes(self, db: AsyncSession) -> list[PanelNode]:
        result = await db.execute(select(PanelNode).order_by(PanelNode.name.asc()))
        return list(result.scalars().all())

    async def list_unassigned_allocations(self, db: AsyncSession, node_id: int) -> list[Allocation]:
        result = await db.execute(
            select(Allocation)
            .where(Allocation.node_id == node_id, Allocation.server_id.is_(None))
            .order_by(Allocation.port.asc())
        )
        return list(result.scalars().all())

    async def list_eggs(self, db: AsyncSession, nest_id: int) -> list[Egg]:
        result = await db.execute(select(Egg).where(Egg.nest_id == nest_id).order_by(Egg.name.asc()))
        return list(result.scalars().all())

    async def get_egg(self, db: AsyncSession, egg_id: int) -> Egg | None:
        return await db.get(Egg, egg_id)

    async def list_egg_variables(self, db: AsyncSession, egg_id: int) -> list[EggVariable]:
        result = await db.execute(
            select(EggVariable)
            .where(EggVariable.egg_id == egg_id)
            .order_by(EggVariable.id.asc())
        )
        return list(result.scalars().all())


resource_repository = ResourceRepository()
