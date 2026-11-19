"""Business logic for Nest, Egg, EggVariable lifecycle and PTDL import/export."""

from __future__ import annotations

import json
import re
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.egg_credentials import EGG_REQUIRED_CREDENTIALS
from app.core.time import to_iso_z, utc_naive_now_sec
from app.db.models.billing import BillingPlan
from app.db.models.manager import Agreement
from app.db.models.pterodactyl import (
    Egg,
    EggVariable,
    Nest,
    PteroServer,
    parse_egg_docker_images,
    parse_json_str_list,
)
from app.schemas.admin_nests_eggs import (
    ENV_VAR_RE,
    RESERVED_ENV_NAMES,
    AffectedPlanWarning,
    EggCreateIn,
    EggDetailOut,
    EggEffectiveConfig,
    EggEffectiveScripts,
    EggRef,
    EggScriptsUpdateIn,
    EggSummaryOut,
    EggUpdateIn,
    EggVariableCreateIn,
    EggVariableOut,
    EggVariableUpdateIn,
    NestCreateIn,
    NestDetailOut,
    NestOut,
    NestUpdateIn,
)
from app.services.billing.plans import (
    PlanValidationError,
    _check_docker_image_in_egg,
    _validate_env_defaults,
)
from app.services.egg_validator import validate_rules_syntax
from app.services.node_management import AdminResourceError

DEFAULT_AUTHOR_EMAIL = "admin@erocraft.com"
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def _valid_author(candidate: str | None) -> str:
    if candidate:
        s = candidate.strip()
        if _EMAIL_RE.match(s) and len(s) <= 191:
            return s
    return DEFAULT_AUTHOR_EMAIL


def _serialize_variable(var: EggVariable) -> EggVariableOut:
    return EggVariableOut(
        id=var.id,
        egg_id=var.egg_id,
        name=var.name,
        description=var.description,
        env_variable=var.env_variable,
        default_value=var.default_value,
        user_viewable=bool(var.user_viewable),
        user_editable=bool(var.user_editable),
        rules=var.rules or "",
        created_at=to_iso_z(var.created_at),
        updated_at=to_iso_z(var.updated_at),
    )


# ---------------------------------------------------------------------------
# Billing plan drift detection
# ---------------------------------------------------------------------------


async def detect_affected_plans(
    db: AsyncSession,
    egg: Egg,
) -> list[AffectedPlanWarning]:
    """Check billing plans referencing this egg for image or env_defaults drift.

    Does not block the egg mutation; returned warnings let admins fix active
    plans before customers hit checkout/apply errors.
    """
    plans = (
        await db.execute(
            select(BillingPlan)
            .where(BillingPlan.egg_id == egg.id)
            .order_by(BillingPlan.id.asc())
        )
    ).scalars().all()
    if not plans:
        return []

    egg_variables = (
        await db.execute(select(EggVariable).where(EggVariable.egg_id == egg.id))
    ).scalars().all()

    warnings: list[AffectedPlanWarning] = []
    for plan in plans:
        reasons: list[str] = []
        try:
            _check_docker_image_in_egg(egg, plan.docker_image)
        except PlanValidationError as exc:
            reasons.append(str(exc))

        try:
            await _validate_env_defaults(
                db,
                egg.id,
                plan.env_defaults or {},
                egg_variables=egg_variables,
            )
        except PlanValidationError as exc:
            reasons.append(str(exc))

        if reasons:
            warnings.append(
                AffectedPlanWarning(
                    id=int(plan.id),
                    code=plan.code,
                    name=plan.display_name,
                    is_active=bool(plan.is_active),
                    reason="；".join(reasons),
                )
            )
    return warnings


# ---------------------------------------------------------------------------
# 1-hop DAG invariant validation for config_from & copy_script_from
# ---------------------------------------------------------------------------


async def _validate_inheritance_target(
    db: AsyncSession,
    *,
    egg_id: int | None,
    nest_id: int,
    parent_id: int | None,
    field: str,
) -> None:
    """Enforce the 1-hop DAG invariant on ``config_from`` or ``copy_script_from``.

    Pterodactyl's Egg accessors (and wings_remote_config.py) only dereference
    one level of inheritance, so parent must be in the same nest, cannot be
    self, cannot itself inherit from another egg, and current egg cannot point
    to a parent if other eggs already depend on it.
    """
    if parent_id is None:
        return

    if egg_id is not None and parent_id == egg_id:
        raise AdminResourceError(422, f"{field} 不能引用自身")

    parent = await db.get(Egg, parent_id)
    if parent is None:
        raise AdminResourceError(422, f"{field} 指向的父 Egg (id={parent_id}) 不存在")
    if parent.nest_id != nest_id:
        raise AdminResourceError(422, f"{field} 只能引用同一预设组 (nest_id={nest_id}) 内的 Egg")

    parent_upstream = getattr(parent, field)
    if parent_upstream is not None:
        raise AdminResourceError(
            422,
            f"目标 Egg '{parent.name}' (id={parent.id}) 自身已设置了 {field}，禁止多跳链式继承",
        )

    if egg_id is not None:
        col = Egg.config_from if field == "config_from" else Egg.copy_script_from
        dependents = int(
            (
                await db.execute(
                    select(func.count(Egg.id)).where(col == egg_id)
                )
            ).scalar_one()
        )
        if dependents > 0:
            raise AdminResourceError(
                422,
                f"当前 Egg 已被 {dependents} 个子 Egg 通过 {field} 引用，禁止再指向其他父 Egg",
            )


# ---------------------------------------------------------------------------
# Nests
# ---------------------------------------------------------------------------


async def list_nests(db: AsyncSession) -> list[NestOut]:
    nests = (await db.execute(select(Nest).order_by(Nest.id.asc()))).scalars().all()
    if not nests:
        return []

    eggs_counts = {
        int(r[0]): int(r[1])
        for r in (
            await db.execute(select(Egg.nest_id, func.count(Egg.id)).group_by(Egg.nest_id))
        ).all()
    }
    servers_counts = {
        int(r[0]): int(r[1])
        for r in (
            await db.execute(
                select(PteroServer.nest_id, func.count(PteroServer.id))
                .where(PteroServer.nest_id.isnot(None))
                .group_by(PteroServer.nest_id)
            )
        ).all()
    }

    return [
        NestOut(
            id=n.id,
            uuid=n.uuid,
            author=n.author,
            name=n.name,
            description=n.description,
            eggs_count=eggs_counts.get(n.id, 0),
            servers_count=servers_counts.get(n.id, 0),
            created_at=to_iso_z(n.created_at),
            updated_at=to_iso_z(n.updated_at),
        )
        for n in nests
    ]


async def get_nest_detail(db: AsyncSession, nest_id: int) -> NestDetailOut:
    nest = await db.get(Nest, nest_id)
    if nest is None:
        raise AdminResourceError(404, f"预设组 {nest_id} 不存在")

    eggs = await list_eggs(db, nest_id=nest_id)
    servers_count = int(
        (
            await db.execute(
                select(func.count(PteroServer.id)).where(PteroServer.nest_id == nest_id)
            )
        ).scalar_one()
    )
    return NestDetailOut(
        id=nest.id,
        uuid=nest.uuid,
        author=nest.author,
        name=nest.name,
        description=nest.description,
        eggs_count=len(eggs),
        servers_count=servers_count,
        created_at=to_iso_z(nest.created_at),
        updated_at=to_iso_z(nest.updated_at),
        eggs=eggs,
    )


async def create_nest(
    db: AsyncSession,
    payload: NestCreateIn,
    *,
    author_email: str | None,
) -> NestOut:
    now = utc_naive_now_sec()
    nest = Nest(
        uuid=str(_uuid.uuid4()),
        author=_valid_author(author_email),
        name=payload.name,
        description=payload.description,
        created_at=now,
        updated_at=now,
    )
    db.add(nest)
    await db.commit()
    await db.refresh(nest)
    return NestOut(
        id=nest.id,
        uuid=nest.uuid,
        author=nest.author,
        name=nest.name,
        description=nest.description,
        eggs_count=0,
        servers_count=0,
        created_at=to_iso_z(nest.created_at),
        updated_at=to_iso_z(nest.updated_at),
    )


async def update_nest(
    db: AsyncSession,
    nest_id: int,
    payload: NestUpdateIn,
) -> NestOut:
    nest = await db.get(Nest, nest_id)
    if nest is None:
        raise AdminResourceError(404, f"预设组 {nest_id} 不存在")

    if "name" in payload.model_fields_set and payload.name is not None:
        nest.name = payload.name
    if "description" in payload.model_fields_set:
        nest.description = payload.description
    nest.updated_at = utc_naive_now_sec()
    await db.commit()
    await db.refresh(nest)

    eggs_count = int(
        (await db.execute(select(func.count(Egg.id)).where(Egg.nest_id == nest.id))).scalar_one()
    )
    servers_count = int(
        (
            await db.execute(
                select(func.count(PteroServer.id)).where(PteroServer.nest_id == nest.id)
            )
        ).scalar_one()
    )
    return NestOut(
        id=nest.id,
        uuid=nest.uuid,
        author=nest.author,
        name=nest.name,
        description=nest.description,
        eggs_count=eggs_count,
        servers_count=servers_count,
        created_at=to_iso_z(nest.created_at),
        updated_at=to_iso_z(nest.updated_at),
    )


async def delete_nest(db: AsyncSession, nest_id: int) -> Nest:
    nest = await db.get(Nest, nest_id)
    if nest is None:
        raise AdminResourceError(404, f"预设组 {nest_id} 不存在")

    # Upstream Panel only checked servers.nest_id, allowing eggs.nest_id ON DELETE CASCADE
    # to silently wipe eggs under a nest with zero servers. Block all three dependencies.
    eggs_count = int(
        (await db.execute(select(func.count(Egg.id)).where(Egg.nest_id == nest_id))).scalar_one()
    )
    if eggs_count > 0:
        raise AdminResourceError(
            409,
            f"预设组 '{nest.name}' 下仍有 {eggs_count} 个 Egg，请先删除全部 Egg",
        )

    servers_count = int(
        (
            await db.execute(
                select(func.count(PteroServer.id)).where(PteroServer.nest_id == nest_id)
            )
        ).scalar_one()
    )
    if servers_count > 0:
        raise AdminResourceError(
            409,
            f"预设组 '{nest.name}' 仍关联 {servers_count} 台服务器，无法删除",
        )

    plans_count = int(
        (
            await db.execute(
                select(func.count(BillingPlan.id)).where(BillingPlan.nest_id == nest_id)
            )
        ).scalar_one()
    )
    if plans_count > 0:
        raise AdminResourceError(
            409,
            f"预设组 '{nest.name}' 仍被 {plans_count} 个计费套餐引用，无法删除",
        )

    snapshot = Nest(id=nest.id, uuid=nest.uuid, author=nest.author, name=nest.name)
    await db.delete(nest)
    await db.commit()
    return snapshot


# ---------------------------------------------------------------------------
# Eggs
# ---------------------------------------------------------------------------


async def list_eggs(
    db: AsyncSession,
    *,
    nest_id: int | None = None,
) -> list[EggSummaryOut]:
    stmt = select(Egg).order_by(Egg.nest_id.asc(), Egg.id.asc())
    if nest_id is not None:
        stmt = stmt.where(Egg.nest_id == nest_id)
    eggs = (await db.execute(stmt)).scalars().all()
    if not eggs:
        return []

    nest_ids = {e.nest_id for e in eggs}
    nest_names = {
        int(r[0]): str(r[1])
        for r in (
            await db.execute(select(Nest.id, Nest.name).where(Nest.id.in_(nest_ids)))
        ).all()
    }
    egg_ids = [e.id for e in eggs]
    server_counts = {
        int(r[0]): int(r[1])
        for r in (
            await db.execute(
                select(PteroServer.egg_id, func.count(PteroServer.id))
                .where(PteroServer.egg_id.in_(egg_ids))
                .group_by(PteroServer.egg_id)
            )
        ).all()
    }
    plan_counts = {
        int(r[0]): int(r[1])
        for r in (
            await db.execute(
                select(BillingPlan.egg_id, func.count(BillingPlan.id))
                .where(BillingPlan.egg_id.in_(egg_ids))
                .group_by(BillingPlan.egg_id)
            )
        ).all()
    }
    var_counts = {
        int(r[0]): int(r[1])
        for r in (
            await db.execute(
                select(EggVariable.egg_id, func.count(EggVariable.id))
                .where(EggVariable.egg_id.in_(egg_ids))
                .group_by(EggVariable.egg_id)
            )
        ).all()
    }

    return [
        EggSummaryOut(
            id=e.id,
            uuid=e.uuid,
            nest_id=e.nest_id,
            nest_name=nest_names.get(e.nest_id, ""),
            author=e.author,
            name=e.name,
            description=e.description,
            docker_images=parse_egg_docker_images(e.docker_images),
            servers_count=server_counts.get(e.id, 0),
            plans_count=plan_counts.get(e.id, 0),
            variables_count=var_counts.get(e.id, 0),
            created_at=to_iso_z(e.created_at),
            updated_at=to_iso_z(e.updated_at),
        )
        for e in eggs
    ]


async def get_egg_detail(db: AsyncSession, egg_id: int) -> EggDetailOut:
    egg = await db.get(Egg, egg_id)
    if egg is None:
        raise AdminResourceError(404, f"Egg {egg_id} 不存在")

    nest = await db.get(Nest, egg.nest_id)
    nest_name = nest.name if nest is not None else ""

    config_parent = (
        await db.get(Egg, egg.config_from) if egg.config_from is not None else None
    )
    script_parent = (
        await db.get(Egg, egg.copy_script_from) if egg.copy_script_from is not None else None
    )

    same_nest_eggs = (
        await db.execute(
            select(Egg).where(Egg.nest_id == egg.nest_id).order_by(Egg.id.asc())
        )
    ).scalars().all()

    dependent_config = [
        EggRef(id=e.id, name=e.name) for e in same_nest_eggs if e.config_from == egg.id
    ]
    dependent_script = [
        EggRef(id=e.id, name=e.name) for e in same_nest_eggs if e.copy_script_from == egg.id
    ]

    # Enforce 1-hop DAG in UI candidate dropdowns: if children already depend on this egg,
    # it cannot inherit from another parent.
    config_candidates = (
        []
        if dependent_config
        else [
            EggRef(id=e.id, name=e.name)
            for e in same_nest_eggs
            if e.id != egg.id and e.config_from is None
        ]
    )
    script_candidates = (
        []
        if dependent_script
        else [
            EggRef(id=e.id, name=e.name)
            for e in same_nest_eggs
            if e.id != egg.id and e.copy_script_from is None
        ]
    )

    variables = (
        await db.execute(
            select(EggVariable)
            .where(EggVariable.egg_id == egg.id)
            .order_by(EggVariable.id.asc())
        )
    ).scalars().all()

    servers_count = int(
        (
            await db.execute(
                select(func.count(PteroServer.id)).where(PteroServer.egg_id == egg.id)
            )
        ).scalar_one()
    )
    plans_count = int(
        (
            await db.execute(
                select(func.count(BillingPlan.id)).where(BillingPlan.egg_id == egg.id)
            )
        ).scalar_one()
    )

    return EggDetailOut(
        id=egg.id,
        uuid=egg.uuid,
        nest_id=egg.nest_id,
        nest_name=nest_name,
        author=egg.author,
        name=egg.name,
        description=egg.description,
        features=parse_json_str_list(egg.features, strip_empty=True),
        docker_images=parse_egg_docker_images(egg.docker_images),
        file_denylist=parse_json_str_list(egg.file_denylist, strip_empty=True) or [],
        update_url=egg.update_url,
        config_files=egg.config_files,
        config_startup=egg.config_startup,
        config_logs=egg.config_logs,
        config_stop=egg.config_stop,
        config_from=egg.config_from,
        startup=egg.startup,
        script_container=egg.script_container,
        copy_script_from=egg.copy_script_from,
        script_entry=egg.script_entry,
        script_is_privileged=bool(egg.script_is_privileged),
        script_install=egg.script_install,
        force_outgoing_ip=bool(egg.force_outgoing_ip),
        created_at=to_iso_z(egg.created_at),
        updated_at=to_iso_z(egg.updated_at),
        effective_config=EggEffectiveConfig(
            config_files=egg.resolve_config_files(config_parent),
            config_startup=egg.resolve_config_startup(config_parent),
            config_logs=egg.resolve_config_logs(config_parent),
            config_stop=egg.resolve_config_stop(config_parent),
            features=egg.resolve_features(config_parent) or [],
            file_denylist=egg.resolve_file_denylist(config_parent) or [],
        ),
        effective_scripts=EggEffectiveScripts(
            script_install=egg.resolve_script_install(script_parent),
            script_container=egg.resolve_script_container(script_parent),
            script_entry=egg.resolve_script_entry(script_parent),
            script_is_privileged=bool(egg.script_is_privileged),
        ),
        config_from_candidates=config_candidates,
        copy_script_from_candidates=script_candidates,
        dependent_config_eggs=dependent_config,
        dependent_script_eggs=dependent_script,
        variables=[_serialize_variable(v) for v in variables],
        servers_count=servers_count,
        plans_count=plans_count,
        in_special_registry=(egg.name in EGG_REQUIRED_CREDENTIALS),
    )


async def create_egg(
    db: AsyncSession,
    payload: EggCreateIn,
    *,
    author_email: str | None,
) -> EggDetailOut:
    nest = await db.get(Nest, payload.nest_id)
    if nest is None:
        raise AdminResourceError(422, f"预设组 nest_id={payload.nest_id} 不存在")

    await _validate_inheritance_target(
        db,
        egg_id=None,
        nest_id=payload.nest_id,
        parent_id=payload.config_from,
        field="config_from",
    )
    await _validate_inheritance_target(
        db,
        egg_id=None,
        nest_id=payload.nest_id,
        parent_id=payload.copy_script_from,
        field="copy_script_from",
    )

    now = utc_naive_now_sec()
    egg = Egg(
        uuid=str(_uuid.uuid4()),
        nest_id=payload.nest_id,
        author=_valid_author(author_email),
        name=payload.name,
        description=payload.description,
        features=json.dumps(payload.features, ensure_ascii=False)
        if payload.features is not None
        else None,
        docker_images=json.dumps(payload.docker_images, ensure_ascii=False),
        file_denylist=json.dumps(payload.file_denylist or [], ensure_ascii=False),
        update_url=payload.update_url,
        config_files=payload.config_files,
        config_startup=payload.config_startup,
        config_logs=payload.config_logs,
        config_stop=payload.config_stop,
        config_from=payload.config_from,
        startup=payload.startup,
        script_container=payload.script_container,
        copy_script_from=payload.copy_script_from,
        script_entry=payload.script_entry,
        script_is_privileged=payload.script_is_privileged,
        script_install=payload.script_install,
        force_outgoing_ip=payload.force_outgoing_ip,
        created_at=now,
        updated_at=now,
    )
    db.add(egg)
    await db.commit()
    await db.refresh(egg)
    return await get_egg_detail(db, egg.id)


async def update_egg(
    db: AsyncSession,
    egg_id: int,
    payload: EggUpdateIn,
) -> tuple[EggDetailOut, list[AffectedPlanWarning]]:
    egg = await db.get(Egg, egg_id)
    if egg is None:
        raise AdminResourceError(404, f"Egg {egg_id} 不存在")

    fields = payload.model_fields_set
    new_config_from = payload.config_from if "config_from" in fields else egg.config_from
    if "config_from" in fields:
        await _validate_inheritance_target(
            db,
            egg_id=egg.id,
            nest_id=egg.nest_id,
            parent_id=new_config_from,
            field="config_from",
        )

    new_config_files = payload.config_files if "config_files" in fields else egg.config_files
    new_config_startup = (
        payload.config_startup if "config_startup" in fields else egg.config_startup
    )
    new_config_logs = payload.config_logs if "config_logs" in fields else egg.config_logs
    new_config_stop = payload.config_stop if "config_stop" in fields else egg.config_stop

    if new_config_from is None:
        if not new_config_stop:
            raise AdminResourceError(422, "未设置 config_from 时，config_stop 为必填项")
        if new_config_files is None:
            raise AdminResourceError(422, "未设置 config_from 时，config_files 为必填项")
        if new_config_startup is None:
            raise AdminResourceError(422, "未设置 config_from 时，config_startup 为必填项")
        if new_config_logs is None:
            raise AdminResourceError(422, "未设置 config_from 时，config_logs 为必填项")

    if "name" in fields and payload.name is not None:
        egg.name = payload.name
    if "description" in fields:
        egg.description = payload.description
    if "features" in fields:
        egg.features = (
            json.dumps(payload.features, ensure_ascii=False)
            if payload.features is not None
            else None
        )
    if "docker_images" in fields and payload.docker_images is not None:
        egg.docker_images = json.dumps(payload.docker_images, ensure_ascii=False)
    if "file_denylist" in fields:
        egg.file_denylist = json.dumps(payload.file_denylist or [], ensure_ascii=False)
    if "update_url" in fields:
        egg.update_url = payload.update_url
    if "startup" in fields and payload.startup is not None:
        egg.startup = payload.startup
    if "config_from" in fields:
        egg.config_from = new_config_from
    if "config_files" in fields:
        egg.config_files = new_config_files
    if "config_startup" in fields:
        egg.config_startup = new_config_startup
    if "config_logs" in fields:
        egg.config_logs = new_config_logs
    if "config_stop" in fields:
        egg.config_stop = new_config_stop
    if "force_outgoing_ip" in fields and payload.force_outgoing_ip is not None:
        egg.force_outgoing_ip = payload.force_outgoing_ip

    egg.updated_at = utc_naive_now_sec()
    await db.commit()
    await db.refresh(egg)

    affected = await detect_affected_plans(db, egg)
    detail = await get_egg_detail(db, egg.id)
    return detail, affected


async def update_egg_scripts(
    db: AsyncSession,
    egg_id: int,
    payload: EggScriptsUpdateIn,
) -> EggDetailOut:
    egg = await db.get(Egg, egg_id)
    if egg is None:
        raise AdminResourceError(404, f"Egg {egg_id} 不存在")

    fields = payload.model_fields_set
    if "copy_script_from" in fields:
        await _validate_inheritance_target(
            db,
            egg_id=egg.id,
            nest_id=egg.nest_id,
            parent_id=payload.copy_script_from,
            field="copy_script_from",
        )
        egg.copy_script_from = payload.copy_script_from

    if "script_install" in fields:
        egg.script_install = payload.script_install
    if "script_is_privileged" in fields and payload.script_is_privileged is not None:
        egg.script_is_privileged = payload.script_is_privileged
    if "script_container" in fields and payload.script_container is not None:
        egg.script_container = payload.script_container
    if "script_entry" in fields and payload.script_entry is not None:
        egg.script_entry = payload.script_entry

    egg.updated_at = utc_naive_now_sec()
    await db.commit()
    return await get_egg_detail(db, egg.id)


async def delete_egg(db: AsyncSession, egg_id: int) -> Egg:
    egg = await db.get(Egg, egg_id)
    if egg is None:
        raise AdminResourceError(404, f"Egg {egg_id} 不存在")

    servers_count = int(
        (
            await db.execute(
                select(func.count(PteroServer.id)).where(PteroServer.egg_id == egg_id)
            )
        ).scalar_one()
    )
    if servers_count > 0:
        raise AdminResourceError(
            409, f"Egg '{egg.name}' 仍关联 {servers_count} 台服务器，无法删除"
        )

    config_children = int(
        (
            await db.execute(
                select(func.count(Egg.id)).where(Egg.config_from == egg_id)
            )
        ).scalar_one()
    )
    if config_children > 0:
        raise AdminResourceError(
            409, f"仍有 {config_children} 个子 Egg 继承此 Egg 的配置 (config_from)，无法删除"
        )

    script_children = int(
        (
            await db.execute(
                select(func.count(Egg.id)).where(Egg.copy_script_from == egg_id)
            )
        ).scalar_one()
    )
    if script_children > 0:
        raise AdminResourceError(
            409,
            f"仍有 {script_children} 个子 Egg 继承此 Egg 的安装脚本 (copy_script_from)，无法删除",
        )

    plans_count = int(
        (
            await db.execute(
                select(func.count(BillingPlan.id)).where(BillingPlan.egg_id == egg_id)
            )
        ).scalar_one()
    )
    if plans_count > 0:
        raise AdminResourceError(
            409,
            f"Egg '{egg.name}' 仍被 {plans_count} 个计费套餐引用，请先修改或删除相关套餐",
        )

    agreements_count = int(
        (
            await db.execute(
                select(func.count(Agreement.id)).where(
                    Agreement.scope == "egg",
                    Agreement.egg_id == egg_id,
                )
            )
        ).scalar_one()
    )
    if agreements_count > 0:
        raise AdminResourceError(
            409,
            f"Egg '{egg.name}' 仍被 {agreements_count} 份 Egg 专属协议引用，请先删除或解绑相关协议",
        )

    snapshot = Egg(
        id=egg.id,
        uuid=egg.uuid,
        nest_id=egg.nest_id,
        author=egg.author,
        name=egg.name,
        script_container=egg.script_container,
        script_entry=egg.script_entry,
    )
    await db.delete(egg)
    await db.commit()
    return snapshot


# ---------------------------------------------------------------------------
# Egg Import (PTDL_v1 & PTDL_v2) & Export (PTDL_v2)
# ---------------------------------------------------------------------------


def _coerce_config_json_str(value: Any, field_label: str) -> str:
    if value is None:
        return "{}"
    if isinstance(value, dict):
        return json.dumps(value, indent=4, ensure_ascii=False)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return "{}"
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError as exc:
            raise AdminResourceError(
                422, f"导入 JSON 的 {field_label} 不是合法 JSON: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise AdminResourceError(422, f"导入 JSON 的 {field_label} 必须是 JSON 对象")
        return s
    raise AdminResourceError(422, f"导入 JSON 的 {field_label} 格式不受支持")


def _parse_and_normalize_egg_json(
    raw: dict[str, Any],
    *,
    fallback_author: str | None,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise AdminResourceError(422, "Egg JSON 根节点必须是对象")

    meta = raw.get("meta")
    if not isinstance(meta, dict) or meta.get("version") not in ("PTDL_v1", "PTDL_v2"):
        raise AdminResourceError(
            422,
            "无法识别的 Egg JSON 格式：meta.version 必须为 PTDL_v1 或 PTDL_v2",
        )
    version = str(meta["version"])

    # Upgrade PTDL_v1 images/image -> docker_images
    docker_images_raw: dict[str, str] = {}
    if version == "PTDL_v1":
        raw_images = raw.get("images")
        if raw_images is not None:
            if not isinstance(raw_images, list):
                raise AdminResourceError(422, "PTDL_v1 的 images 必须是字符串数组")
            for img in raw_images:
                if not isinstance(img, str):
                    raise AdminResourceError(422, "PTDL_v1 的 images 数组元素必须是字符串")
                stripped = img.strip()
                if not stripped:
                    raise AdminResourceError(422, "Docker 镜像键名和镜像地址均不能为空")
                docker_images_raw[stripped] = stripped
        if not docker_images_raw:
            raw_image = raw.get("image")
            if raw_image is not None:
                if not isinstance(raw_image, str):
                    raise AdminResourceError(422, "PTDL_v1 的 image 必须是字符串")
                single = raw_image.strip()
                if single:
                    docker_images_raw[single] = single
    else:
        raw_di = raw.get("docker_images")
        if isinstance(raw_di, dict):
            for k, v in raw_di.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    raise AdminResourceError(
                        422, "PTDL_v2 的 docker_images 键名和镜像地址均必须是字符串"
                    )
                ks, vs = k.strip(), v.strip()
                if not ks or not vs:
                    raise AdminResourceError(422, "Docker 镜像键名和镜像地址均不能为空")
                docker_images_raw[ks] = vs
        elif isinstance(raw_di, list):
            # Official Panel seed eggs (e.g. Ark) may emit PTDL_v2 with a list of images
            for img in raw_di:
                if not isinstance(img, str):
                    raise AdminResourceError(
                        422, "PTDL_v2 的 docker_images 数组元素必须是字符串"
                    )
                stripped = img.strip()
                if not stripped:
                    raise AdminResourceError(422, "Docker 镜像键名和镜像地址均不能为空")
                docker_images_raw[stripped] = stripped
        else:
            raise AdminResourceError(422, "PTDL_v2 缺少合法的 docker_images 对象或数组")

    if not docker_images_raw:
        raise AdminResourceError(422, "导入的 Egg 至少需要包含一个 Docker 镜像")
    for k, v in docker_images_raw.items():
        if len(v) > 191:
            raise AdminResourceError(422, f"Docker 镜像地址长度超过 191: {v[:40]}...")

    name = str(raw.get("name") or "").strip()
    if not name or len(name) > 191:
        raise AdminResourceError(422, "导入 JSON 缺少合法的 name 字段（长度 1~191）")

    startup = raw.get("startup")
    if startup is None or not str(startup).strip():
        raise AdminResourceError(422, "导入 JSON 缺少合法的 startup 启动命令")

    raw_features = raw.get("features")
    if raw_features is None:
        features_list: list[str] | None = None
    elif isinstance(raw_features, list):
        features_list = [str(x).strip() for x in raw_features if str(x).strip()]
    else:
        raise AdminResourceError(422, "导入 JSON 的 features 必须是数组或 null")

    raw_denylist = raw.get("file_denylist")
    if raw_denylist is None:
        denylist: list[str] = []
    elif isinstance(raw_denylist, list):
        denylist = [str(x).strip() for x in raw_denylist if str(x).strip()]
    elif isinstance(raw_denylist, dict):
        # Tolerate PHP Collection::filter() associative object output
        denylist = [str(v).strip() for v in raw_denylist.values() if str(v).strip()]
    else:
        raise AdminResourceError(422, "导入 JSON 的 file_denylist 格式无效")

    cfg = raw.get("config")
    if not isinstance(cfg, dict):
        raise AdminResourceError(422, "导入 JSON 缺少 config 对象")

    config_files = _coerce_config_json_str(cfg.get("files"), "config.files")
    config_startup = _coerce_config_json_str(cfg.get("startup"), "config.startup")
    config_logs = _coerce_config_json_str(cfg.get("logs"), "config.logs")
    config_stop_val = cfg.get("stop")
    if config_stop_val is not None and not isinstance(config_stop_val, str):
        raise AdminResourceError(422, "导入 JSON 的 config.stop 必须是字符串或 null")
    config_stop = config_stop_val.strip() if isinstance(config_stop_val, str) else ""
    if len(config_stop) > 191:
        raise AdminResourceError(422, "config.stop 长度不能超过 191")

    scripts = raw.get("scripts") or {}
    install_block = scripts.get("installation") if isinstance(scripts, dict) else {}
    if not isinstance(install_block, dict):
        install_block = {}

    script_install_raw = install_block.get("script")
    if script_install_raw is not None:
        script_install_str = str(script_install_raw)
        script_install: str | None = script_install_str if script_install_str.strip() else None
    else:
        script_install = None
    script_container = str(install_block.get("container") or "").strip() or "alpine:3.4"
    script_entry = str(install_block.get("entrypoint") or "").strip() or "ash"
    if len(script_container) > 191 or len(script_entry) > 191:
        raise AdminResourceError(422, "安装脚本 container 或 entrypoint 长度不能超过 191")

    raw_vars = raw.get("variables") or []
    if not isinstance(raw_vars, list):
        raise AdminResourceError(422, "导入 JSON 的 variables 必须是数组")

    seen_env: set[str] = set()
    normalized_vars: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_vars):
        if not isinstance(item, dict):
            raise AdminResourceError(422, f"variables[{idx}] 必须是对象")
        v_name = str(item.get("name") or "").strip()
        if not v_name or len(v_name) > 191:
            raise AdminResourceError(422, f"variables[{idx}].name 无效")
        env_var = str(item.get("env_variable") or "").strip()
        if not ENV_VAR_RE.match(env_var):
            raise AdminResourceError(422, f"variables[{idx}].env_variable '{env_var}' 格式无效")
        if env_var.upper() in RESERVED_ENV_NAMES:
            raise AdminResourceError(
                422, f"variables[{idx}].env_variable '{env_var}' 为系统保留名称"
            )
        if env_var in seen_env:
            raise AdminResourceError(
                422, f"导入 JSON 包含重复的环境变量名: '{env_var}'"
            )
        seen_env.add(env_var)

        raw_rules = str(item.get("rules") or "").strip()
        try:
            validated_rules = validate_rules_syntax(raw_rules)
        except ValueError as exc:
            raise AdminResourceError(
                422, f"变量 '{env_var}' 的校验规则无效: {exc}"
            ) from exc

        dv_raw = item.get("default_value")
        if dv_raw is None:
            default_value = ""
        elif isinstance(dv_raw, bool):
            default_value = "1" if dv_raw else "0"
        else:
            default_value = str(dv_raw)

        desc_raw = item.get("description")
        description = "" if desc_raw is None else str(desc_raw)

        normalized_vars.append(
            {
                "name": v_name,
                "description": description,
                "env_variable": env_var,
                "default_value": default_value,
                "user_viewable": 1 if bool(item.get("user_viewable", False)) else 0,
                "user_editable": 1 if bool(item.get("user_editable", False)) else 0,
                "rules": validated_rules,
            }
        )

    raw_author = raw.get("author")
    author = _valid_author(str(raw_author) if raw_author is not None else fallback_author)

    update_url_raw = meta.get("update_url")
    update_url = str(update_url_raw).strip() if update_url_raw else None

    desc_raw = raw.get("description")
    egg_desc = str(desc_raw) if desc_raw is not None else None

    return {
        "name": name,
        "author": author,
        "description": egg_desc,
        "features": json.dumps(features_list, ensure_ascii=False)
        if features_list is not None
        else None,
        "docker_images": json.dumps(docker_images_raw, ensure_ascii=False),
        "file_denylist": json.dumps(denylist, ensure_ascii=False),
        "update_url": update_url,
        "config_files": config_files,
        "config_startup": config_startup,
        "config_logs": config_logs,
        "config_stop": config_stop or None,
        "startup": str(startup),
        "script_install": script_install,
        "script_container": script_container,
        "script_entry": script_entry,
        "variables": normalized_vars,
    }


async def import_egg_new(
    db: AsyncSession,
    *,
    nest_id: int,
    raw_json: dict[str, Any],
    fallback_author: str | None,
) -> EggDetailOut:
    nest = await db.get(Nest, nest_id)
    if nest is None:
        raise AdminResourceError(404, f"预设组 nest_id={nest_id} 不存在")

    parsed = _parse_and_normalize_egg_json(raw_json, fallback_author=fallback_author)
    if not parsed["config_stop"]:
        raise AdminResourceError(422, "导入 JSON 缺少合法的 config.stop 停止命令")
    now = utc_naive_now_sec()
    egg = Egg(
        uuid=str(_uuid.uuid4()),
        nest_id=nest_id,
        author=parsed["author"],
        name=parsed["name"],
        description=parsed["description"],
        features=parsed["features"],
        docker_images=parsed["docker_images"],
        file_denylist=parsed["file_denylist"],
        update_url=parsed["update_url"],
        config_files=parsed["config_files"],
        config_startup=parsed["config_startup"],
        config_logs=parsed["config_logs"],
        config_stop=parsed["config_stop"],
        config_from=None,
        startup=parsed["startup"],
        script_container=parsed["script_container"],
        copy_script_from=None,
        script_entry=parsed["script_entry"],
        script_is_privileged=True,
        script_install=parsed["script_install"],
        force_outgoing_ip=False,
        created_at=now,
        updated_at=now,
    )
    db.add(egg)
    await db.flush()

    for v in parsed["variables"]:
        db.add(
            EggVariable(
                egg_id=egg.id,
                name=v["name"],
                description=v["description"],
                env_variable=v["env_variable"],
                default_value=v["default_value"],
                user_viewable=v["user_viewable"],
                user_editable=v["user_editable"],
                rules=v["rules"],
                created_at=now,
                updated_at=now,
            )
        )

    await db.commit()
    return await get_egg_detail(db, egg.id)


async def import_egg_overwrite(
    db: AsyncSession,
    *,
    egg_id: int,
    raw_json: dict[str, Any],
) -> tuple[EggDetailOut, list[AffectedPlanWarning]]:
    egg = await db.get(Egg, egg_id)
    if egg is None:
        raise AdminResourceError(404, f"Egg {egg_id} 不存在")

    parsed = _parse_and_normalize_egg_json(raw_json, fallback_author=egg.author)
    if egg.config_from is None and not parsed["config_stop"]:
        raise AdminResourceError(422, "导入 JSON 缺少合法的 config.stop 停止命令")
    now = utc_naive_now_sec()

    # Preserve id, uuid, nest_id, author, config_from, copy_script_from,
    # script_is_privileged, force_outgoing_ip (matches EggUpdateImporterService).
    egg.name = parsed["name"]
    egg.description = parsed["description"]
    egg.features = parsed["features"]
    egg.docker_images = parsed["docker_images"]
    egg.file_denylist = parsed["file_denylist"]
    egg.update_url = parsed["update_url"]
    egg.config_files = parsed["config_files"]
    egg.config_startup = parsed["config_startup"]
    egg.config_logs = parsed["config_logs"]
    egg.config_stop = parsed["config_stop"]
    egg.startup = parsed["startup"]
    egg.script_install = parsed["script_install"]
    egg.script_container = parsed["script_container"]
    egg.script_entry = parsed["script_entry"]
    egg.updated_at = now

    existing_vars = (
        await db.execute(
            select(EggVariable).where(EggVariable.egg_id == egg.id)
        )
    ).scalars().all()
    existing_by_env = {v.env_variable: v for v in existing_vars}
    imported_envs: set[str] = set()

    # In-place update preserves egg_variables.id so existing server_variables rows stay intact.
    for v in parsed["variables"]:
        env_name = v["env_variable"]
        imported_envs.add(env_name)
        current = existing_by_env.get(env_name)
        if current is not None:
            current.name = v["name"]
            current.description = v["description"]
            current.default_value = v["default_value"]
            current.user_viewable = v["user_viewable"]
            current.user_editable = v["user_editable"]
            current.rules = v["rules"]
            current.updated_at = now
        else:
            db.add(
                EggVariable(
                    egg_id=egg.id,
                    name=v["name"],
                    description=v["description"],
                    env_variable=env_name,
                    default_value=v["default_value"],
                    user_viewable=v["user_viewable"],
                    user_editable=v["user_editable"],
                    rules=v["rules"],
                    created_at=now,
                    updated_at=now,
                )
            )

    for old_env, old_var in existing_by_env.items():
        if old_env not in imported_envs:
            await db.delete(old_var)

    await db.commit()
    await db.refresh(egg)

    affected = await detect_affected_plans(db, egg)
    detail = await get_egg_detail(db, egg.id)
    return detail, affected


async def export_egg_json(db: AsyncSession, egg_id: int) -> tuple[str, str]:
    """Return ``(filename, json_text)`` matching Panel EggExporterService PTDL_v2."""
    egg = await db.get(Egg, egg_id)
    if egg is None:
        raise AdminResourceError(404, f"Egg {egg_id} 不存在")

    config_parent = (
        await db.get(Egg, egg.config_from) if egg.config_from is not None else None
    )
    script_parent = (
        await db.get(Egg, egg.copy_script_from) if egg.copy_script_from is not None else None
    )
    variables = (
        await db.execute(
            select(EggVariable)
            .where(EggVariable.egg_id == egg.id)
            .order_by(EggVariable.id.asc())
        )
    ).scalars().all()

    file_denylist = [
        item for item in (egg.resolve_file_denylist(config_parent) or []) if item
    ]

    struct: dict[str, Any] = {
        "_comment": "DO NOT EDIT: FILE GENERATED AUTOMATICALLY BY PTERODACTYL PANEL - PTERODACTYL.IO",
        "meta": {
            "version": "PTDL_v2",
            "update_url": egg.update_url,
        },
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "name": egg.name,
        "author": egg.author,
        "description": egg.description,
        "features": parse_json_str_list(egg.features, strip_empty=True),
        "docker_images": parse_egg_docker_images(egg.docker_images),
        "file_denylist": file_denylist,
        "startup": egg.startup,
        "config": {
            "files": egg.resolve_config_files(config_parent),
            "startup": egg.resolve_config_startup(config_parent),
            "logs": egg.resolve_config_logs(config_parent),
            "stop": egg.resolve_config_stop(config_parent),
        },
        "scripts": {
            "installation": {
                "script": egg.resolve_script_install(script_parent),
                "container": egg.resolve_script_container(script_parent),
                "entrypoint": egg.resolve_script_entry(script_parent),
            }
        },
        "variables": [
            {
                "name": v.name,
                "description": v.description,
                "env_variable": v.env_variable,
                "default_value": v.default_value,
                "user_viewable": bool(v.user_viewable),
                "user_editable": bool(v.user_editable),
                "rules": v.rules or "",
                "field_type": "text",
            }
            for v in variables
        ],
    }

    slug = _SLUG_STRIP_RE.sub("-", egg.name.lower()).strip("-")
    filename = f"egg-{slug or egg.id}.json"
    return filename, json.dumps(struct, indent=4, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Egg Variables
# ---------------------------------------------------------------------------


async def create_egg_variable(
    db: AsyncSession,
    egg_id: int,
    payload: EggVariableCreateIn,
) -> tuple[EggVariableOut, list[AffectedPlanWarning]]:
    egg = await db.get(Egg, egg_id)
    if egg is None:
        raise AdminResourceError(404, f"Egg {egg_id} 不存在")

    dup = (
        await db.execute(
            select(EggVariable.id).where(
                EggVariable.egg_id == egg_id,
                EggVariable.env_variable == payload.env_variable,
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise AdminResourceError(
            409, f"环境变量 '{payload.env_variable}' 在当前 Egg 中已存在"
        )

    now = utc_naive_now_sec()
    var = EggVariable(
        egg_id=egg_id,
        name=payload.name,
        description=payload.description or "",
        env_variable=payload.env_variable,
        default_value=payload.default_value or "",
        user_viewable=1 if payload.user_viewable else 0,
        user_editable=1 if payload.user_editable else 0,
        rules=payload.rules,
        created_at=now,
        updated_at=now,
    )
    db.add(var)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AdminResourceError(
            409, f"环境变量 '{payload.env_variable}' 已存在"
        ) from exc
    await db.refresh(var)

    affected = await detect_affected_plans(db, egg)
    return _serialize_variable(var), affected


async def update_egg_variable(
    db: AsyncSession,
    egg_id: int,
    var_id: int,
    payload: EggVariableUpdateIn,
) -> tuple[EggVariableOut, list[AffectedPlanWarning]]:
    egg = await db.get(Egg, egg_id)
    if egg is None:
        raise AdminResourceError(404, f"Egg {egg_id} 不存在")

    var = await db.get(EggVariable, var_id)
    if var is None or var.egg_id != egg_id:
        raise AdminResourceError(404, f"变量 {var_id} 不存在或不属于 Egg {egg_id}")

    fields = payload.model_fields_set
    if "env_variable" in fields and payload.env_variable is not None:
        dup = (
            await db.execute(
                select(EggVariable.id).where(
                    EggVariable.egg_id == egg_id,
                    EggVariable.env_variable == payload.env_variable,
                    EggVariable.id != var_id,
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise AdminResourceError(
                409, f"环境变量 '{payload.env_variable}' 在当前 Egg 中已存在"
            )
        var.env_variable = payload.env_variable

    if "name" in fields and payload.name is not None:
        var.name = payload.name
    if "description" in fields:
        var.description = payload.description or ""
    if "default_value" in fields:
        var.default_value = payload.default_value or ""
    if "user_viewable" in fields and payload.user_viewable is not None:
        var.user_viewable = 1 if payload.user_viewable else 0
    if "user_editable" in fields and payload.user_editable is not None:
        var.user_editable = 1 if payload.user_editable else 0
    if "rules" in fields and payload.rules is not None:
        var.rules = payload.rules

    var.updated_at = utc_naive_now_sec()
    await db.commit()
    await db.refresh(var)

    affected = await detect_affected_plans(db, egg)
    return _serialize_variable(var), affected


async def delete_egg_variable(
    db: AsyncSession,
    egg_id: int,
    var_id: int,
) -> tuple[EggVariable, list[AffectedPlanWarning]]:
    egg = await db.get(Egg, egg_id)
    if egg is None:
        raise AdminResourceError(404, f"Egg {egg_id} 不存在")

    var = await db.get(EggVariable, var_id)
    if var is None or var.egg_id != egg_id:
        raise AdminResourceError(404, f"变量 {var_id} 不存在或不属于 Egg {egg_id}")

    snapshot = EggVariable(
        id=var.id,
        egg_id=var.egg_id,
        name=var.name,
        description=var.description,
        env_variable=var.env_variable,
        default_value=var.default_value,
        user_viewable=var.user_viewable,
        user_editable=var.user_editable,
        rules=var.rules,
    )
    await db.delete(var)
    await db.commit()

    affected = await detect_affected_plans(db, egg)
    return snapshot, affected
