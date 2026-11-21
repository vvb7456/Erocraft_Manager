"""邮箱 6 位数字验证码的冷却检查、签发、校验与消费服务。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tokens import (
    VERIFICATION_CODE_COOLDOWN_SECONDS,
    VERIFICATION_CODE_EXPIRY_MINUTES,
    code_digest,
    generate_verification_code,
    verify_verification_code,
)
from app.db.models.manager import ManagerEmailVerificationCode

VerificationPurpose = Literal["register", "password_reset", "email_change"]
VerifyCodeStatus = Literal["ok", "invalid", "expired"]


def _scope_filters(
    *,
    purpose: VerificationPurpose,
    email: str | None = None,
    user_id: int | None = None,
) -> list:
    clauses = [ManagerEmailVerificationCode.purpose == purpose]
    if user_id is not None:
        clauses.append(ManagerEmailVerificationCode.user_id == user_id)
    elif email is not None:
        clauses.append(ManagerEmailVerificationCode.email == email)
    else:
        raise ValueError("Either user_id or email must be provided")
    return clauses


async def is_within_cooldown(
    db: AsyncSession,
    *,
    purpose: VerificationPurpose,
    now: datetime,
    email: str | None = None,
    user_id: int | None = None,
) -> bool:
    latest = await db.scalar(
        select(ManagerEmailVerificationCode)
        .where(*_scope_filters(purpose=purpose, email=email, user_id=user_id))
        .order_by(ManagerEmailVerificationCode.created_at.desc(), ManagerEmailVerificationCode.id.desc())
        .limit(1)
    )
    return bool(
        latest
        and latest.created_at
        and (now - latest.created_at).total_seconds() < VERIFICATION_CODE_COOLDOWN_SECONDS
    )


async def issue_code(
    db: AsyncSession,
    *,
    purpose: VerificationPurpose,
    email: str,
    now: datetime,
    user_id: int | None = None,
) -> tuple[int, str]:
    raw_code = generate_verification_code()
    await db.execute(
        update(ManagerEmailVerificationCode)
        .where(
            *_scope_filters(purpose=purpose, email=email, user_id=user_id),
            ManagerEmailVerificationCode.used_at.is_(None),
        )
        .values(used_at=now)
    )
    record = ManagerEmailVerificationCode(
        purpose=purpose,
        email=email,
        user_id=user_id,
        code_hash=code_digest(purpose, email, raw_code),
        created_at=now,
    )
    db.add(record)
    await db.flush()
    return int(record.id), raw_code


async def delete_code(db: AsyncSession, record_id: int) -> None:
    await db.execute(
        delete(ManagerEmailVerificationCode).where(ManagerEmailVerificationCode.id == record_id)
    )


async def verify_latest_code(
    db: AsyncSession,
    *,
    purpose: VerificationPurpose,
    email: str,
    code: str,
    now: datetime,
    user_id: int | None = None,
) -> tuple[ManagerEmailVerificationCode | None, VerifyCodeStatus]:
    cleaned = code.strip()
    record = (
        await db.execute(
            select(ManagerEmailVerificationCode)
            .where(
                *_scope_filters(purpose=purpose, email=email, user_id=user_id),
                ManagerEmailVerificationCode.used_at.is_(None),
            )
            .order_by(ManagerEmailVerificationCode.created_at.desc(), ManagerEmailVerificationCode.id.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if (
        record is None
        or not cleaned
        or record.email != email
        or not verify_verification_code(purpose, email, cleaned, record.code_hash)
    ):
        return None, "invalid"
    if now - record.created_at >= timedelta(minutes=VERIFICATION_CODE_EXPIRY_MINUTES):
        return record, "expired"
    return record, "ok"


async def consume_code(
    db: AsyncSession,
    record: ManagerEmailVerificationCode,
    now: datetime,
) -> None:
    record.used_at = now
    await db.execute(
        update(ManagerEmailVerificationCode)
        .where(
            *_scope_filters(
                purpose=record.purpose,  # type: ignore[arg-type]
                email=record.email,
                user_id=record.user_id,
            ),
            ManagerEmailVerificationCode.used_at.is_(None),
        )
        .values(used_at=now)
    )


async def revoke_user_codes(
    db: AsyncSession,
    user_id: int,
    now: datetime,
) -> None:
    await db.execute(
        update(ManagerEmailVerificationCode)
        .where(
            ManagerEmailVerificationCode.user_id == user_id,
            ManagerEmailVerificationCode.used_at.is_(None),
        )
        .values(used_at=now)
    )
