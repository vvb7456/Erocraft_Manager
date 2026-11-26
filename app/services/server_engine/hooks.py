"""Best-effort post-commit hooks (Cloudflare Tunnel + NewAPI LLM). Never fail or rollback core mutations."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm_provision import provision as llm_provision
from app.services.tunnel_manager import dispatcher as tunnel_dispatcher

logger = logging.getLogger(__name__)


async def _run_best_effort(
    db: AsyncSession,
    action: Callable[[], Awaitable[Any]],
    *,
    label: str,
    warning_prefix: str,
    commit: bool = False,
) -> list[str]:
    try:
        await action()
        if commit:
            await db.commit()
        return []
    except Exception as exc:  # noqa: BLE001
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning("%s failed", label, exc_info=True)
        return [f"{warning_prefix}: {str(exc)[:200]}"]


async def on_provisioned(
    db: AsyncSession,
    *,
    server_id: int,
    user_id: int,
    plan_snapshot: Mapping[str, Any] | None,
) -> list[str]:
    if not plan_snapshot or not (
        bool(plan_snapshot.get("llm_enabled")) and int(plan_snapshot.get("llm_quota_grant", 0)) > 0
    ):
        return []
    return await _run_best_effort(
        db,
        lambda: llm_provision.provision_for_server(db, server_id, user_id, dict(plan_snapshot)),
        label=f"hooks.on_provisioned(server={server_id})",
        warning_prefix="LLM 额度开通失败",
        commit=True,
    )


async def on_plan_changed(
    db: AsyncSession,
    *,
    server_id: int,
    new_snapshot: Mapping[str, Any] | None,
) -> list[str]:
    return await _run_best_effort(
        db,
        lambda: llm_provision.update_for_upgrade(db, server_id, new_snapshot),
        label=f"hooks.on_plan_changed(server={server_id})",
        warning_prefix="LLM 套餐同步失败",
        commit=True,
    )


async def on_suspended(db: AsyncSession, *, server_id: int, actor: str = "system") -> list[str]:
    return await _run_best_effort(
        db,
        lambda: llm_provision.set_server_llm_enabled(db, server_id, enabled=False, actor=actor),
        label=f"hooks.on_suspended(server={server_id})",
        warning_prefix="LLM 密钥停用同步失败",
        commit=True,
    )


async def on_unsuspended(db: AsyncSession, *, server_id: int, actor: str = "system") -> list[str]:
    return await _run_best_effort(
        db,
        lambda: llm_provision.set_server_llm_enabled(db, server_id, enabled=True, actor=actor),
        label=f"hooks.on_unsuspended(server={server_id})",
        warning_prefix="LLM 密钥恢复同步失败",
        commit=True,
    )


async def on_primary_allocation_changed(db: AsyncSession, *, server_id: int, new_port: int) -> list[str]:
    return await _run_best_effort(
        db,
        lambda: tunnel_dispatcher.on_server_primary_port_changed(db, server_id, new_port),
        label=f"hooks.on_primary_allocation_changed(server={server_id}, port={new_port})",
        warning_prefix="隧道上游端口同步失败",
    )


async def on_deleted(db: AsyncSession, *, server_id: int) -> list[str]:
    warnings = await _run_best_effort(
        db,
        lambda: tunnel_dispatcher.on_server_pre_delete(db, server_id),
        label=f"hooks.on_deleted.tunnel(server={server_id})",
        warning_prefix="隧道清理失败",
    )
    warnings.extend(
        await _run_best_effort(
            db,
            lambda: llm_provision.revoke_for_server(db, server_id),
            label=f"hooks.on_deleted.llm(server={server_id})",
            warning_prefix="LLM 密钥吊销失败",
            commit=True,
        )
    )
    return warnings


__all__ = [
    "on_provisioned",
    "on_plan_changed",
    "on_suspended",
    "on_unsuspended",
    "on_primary_allocation_changed",
    "on_deleted",
]
