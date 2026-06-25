"""User repository helpers."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.manager import UserReferral
from app.db.models.pterodactyl import PteroServer, PteroUser
from app.db.repositories.servers import exclude_placeholders


class UserRepository:
    async def get_by_id(self, db: AsyncSession, user_id: int) -> PteroUser | None:
        return await db.get(PteroUser, user_id)

    async def get_by_username_or_email(
        self,
        db: AsyncSession,
        identifier: str,
    ) -> PteroUser | None:
        result = await db.execute(
            select(PteroUser).where(
                or_(PteroUser.username == identifier, PteroUser.email == identifier)
            )
        )
        return result.scalar_one_or_none()

    async def count(self, db: AsyncSession) -> int:
        result = await db.execute(select(func.count(PteroUser.id)))
        return int(result.scalar_one() or 0)

    async def get_by_email(self, db: AsyncSession, email: str) -> PteroUser | None:
        result = await db.execute(select(PteroUser).where(PteroUser.email == email))
        return result.scalar_one_or_none()

    async def get_by_username(self, db: AsyncSession, username: str) -> PteroUser | None:
        result = await db.execute(select(PteroUser).where(PteroUser.username == username))
        return result.scalar_one_or_none()

    async def list_for_admin(
        self,
        db: AsyncSession,
    ) -> list[tuple[PteroUser, int, int | None, str | None]]:
        Inviter = aliased(PteroUser)
        result = await db.execute(
            select(
                PteroUser,
                func.count(PteroServer.id),
                UserReferral.inviter_user_id,
                Inviter.username,
            )
            .outerjoin(
                PteroServer,
                (PteroServer.owner_id == PteroUser.id) & exclude_placeholders(),
            )
            .outerjoin(
                UserReferral,
                (UserReferral.invitee_user_id == PteroUser.id)
                & (UserReferral.status != "revoked"),
            )
            .outerjoin(Inviter, Inviter.id == UserReferral.inviter_user_id)
            .group_by(PteroUser.id, UserReferral.inviter_user_id, Inviter.username)
            .order_by(PteroUser.id.asc())
        )
        return [
            (user, int(server_count or 0), inviter_id, inviter_username)
            for user, server_count, inviter_id, inviter_username in result.all()
        ]

    async def list_by_ids(
        self,
        db: AsyncSession,
        user_ids: list[int],
    ) -> list[PteroUser]:
        if not user_ids:
            return []
        result = await db.execute(
            select(PteroUser)
            .where(PteroUser.id.in_(user_ids))
            .order_by(PteroUser.id.asc())
        )
        return list(result.scalars().all())

user_repository = UserRepository()
