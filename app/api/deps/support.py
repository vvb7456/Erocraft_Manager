"""A chat participant's role is determined by the authenticated entry point."""

from dataclasses import dataclass

from fastapi import Depends

from app.api.deps.auth import get_current_user
from app.db.models.pterodactyl import PteroUser


@dataclass(frozen=True)
class SupportUser:
    id: int
    username: str
    root_admin: bool = False


async def get_support_user(user: PteroUser = Depends(get_current_user)) -> SupportUser:
    return SupportUser(user.id, user.username, bool(user.root_admin))
