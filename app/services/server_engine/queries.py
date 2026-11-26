from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Allocation, EggVariable, ManagerHost, Nest, PteroServer, ServerVariable
from app.db.models.billing import BillingPlan
from app.db.models.pterodactyl import parse_egg_docker_images
from app.db.repositories.allocation_reservations import is_allocation_free_clause
from app.schemas.admin_server_detail import (
    AdminServerDetailResponse,
    AdminServerSummary,
    DockerImageOption,
    ManagerHostSummary,
    ServerAllocationSummary,
    ServerEggSummary,
    ServerNestSummary,
    ServerNodeSummary,
    ServerOwnerSummary,
    ServerRuntimeResponse,
    ServerVariableSummary,
)
from app.services.runtime import InstanceRuntimeAdapter, wings_runtime_adapter
from app.services.server_engine.errors import ServerNotFoundError


async def get_server_or_404(db: AsyncSession, server_id: int) -> PteroServer:
    server = (await db.execute(select(PteroServer).where(PteroServer.id == server_id))).scalar_one_or_none()
    if server is None:
        raise ServerNotFoundError(f"服务器 {server_id} 不存在")
    return server


async def get_server_detail(db: AsyncSession, server_id: int) -> AdminServerDetailResponse:
    server = await get_server_or_404(db, server_id)
    nest = await db.get(Nest, int(server.nest_id)) if server.nest_id is not None else None
    manager_host = (
        await db.execute(select(ManagerHost).where(ManagerHost.pterodactyl_node_id == server.node_id))
    ).scalar_one_or_none()

    allocations = list(
        (
            await db.execute(
                select(Allocation)
                .where(or_(Allocation.server_id == server_id, Allocation.id == server.allocation_id))
                .order_by(Allocation.id.asc())
            )
        ).scalars().all()
    )
    allocations.sort(key=lambda item: (item.id != server.allocation_id, item.id))

    variable_pairs = list(
        (
            await db.execute(
                select(EggVariable, ServerVariable.variable_value)
                .outerjoin(
                    ServerVariable,
                    and_(ServerVariable.variable_id == EggVariable.id, ServerVariable.server_id == server_id),
                )
                .where(EggVariable.egg_id == server.egg_id)
                .order_by(EggVariable.id.asc())
            )
        ).all()
    )
    plan_obj = await db.get(BillingPlan, server.plan_id) if server.plan_id is not None else None
    docker_images = [
        DockerImageOption(label=label, value=value)
        for label, value in parse_egg_docker_images(server.egg.docker_images, accept_list=True).items()
        if value
    ]

    return AdminServerDetailResponse(
        server=AdminServerSummary(
            id=int(server.id),
            uuid=server.uuid,
            uuid_short=server.uuid_short,
            external_id=server.external_id,
            name=server.name,
            description=server.description or "",
            status=server.status,
            is_suspended=server.is_suspended,
            is_installing=server.status == "installing" or server.installed_at is None,
            owner_id=int(server.owner_id),
            node_id=int(server.node_id),
            nest_id=server.nest_id,
            egg_id=int(server.egg_id),
            allocation_id=int(server.allocation_id),
            memory=int(server.memory),
            swap=int(server.swap),
            disk=int(server.disk),
            io=int(server.io),
            cpu=int(server.cpu),
            threads=server.threads,
            oom_disabled=bool(server.oom_disabled),
            allocation_limit=server.allocation_limit,
            database_limit=server.database_limit,
            backup_limit=int(server.backup_limit),
            image=server.image,
            startup=server.startup,
            skip_scripts=bool(server.skip_scripts),
            created_at=server.created_at,
            updated_at=server.updated_at,
            installed_at=server.installed_at,
            expiration_date=server.expiration_date.isoformat() if server.expiration_date else None,
            is_trial=bool(server.is_trial),
            plan_id=server.plan_id,
            plan_code=plan_obj.code if plan_obj else None,
            plan_name=plan_obj.display_name if plan_obj else None,
            plan_type=plan_obj.plan_type if plan_obj else None,
        ),
        owner=ServerOwnerSummary(
            id=int(server.owner.id),
            uuid=server.owner.uuid,
            username=server.owner.username,
            email=server.owner.email,
        ),
        node=ServerNodeSummary(
            id=int(server.node.id),
            name=server.node.name,
            fqdn=server.node.fqdn,
            scheme=server.node.scheme,
            daemon_listen=int(server.node.daemon_listen),
            daemon_sftp=int(server.node.daemon_sftp),
        ),
        nest=ServerNestSummary(id=int(nest.id), name=nest.name) if nest else None,
        egg=ServerEggSummary(
            id=int(server.egg.id),
            name=server.egg.name,
            nest_id=server.egg.nest_id,
            startup=server.egg.startup,
            docker_images=docker_images,
        ),
        manager_host=(
            ManagerHostSummary(
                id=int(manager_host.id),
                name=manager_host.name,
                agent_url=manager_host.agent_url,
                enabled=bool(manager_host.enabled),
            )
            if manager_host
            else None
        ),
        allocations=[
            ServerAllocationSummary(
                id=int(a.id),
                node_id=int(a.node_id),
                ip=a.ip,
                ip_alias=a.ip_alias,
                port=int(a.port),
                notes=a.notes,
                is_primary=a.id == server.allocation_id,
            )
            for a in allocations
        ],
        variables=[
            ServerVariableSummary(
                id=int(v.id),
                name=v.name,
                description=v.description,
                env_variable=v.env_variable,
                default_value=v.default_value,
                value=(val if val is not None else v.default_value) or "",
                rules=v.rules,
                user_viewable=bool(v.user_viewable),
                user_editable=bool(v.user_editable),
            )
            for v, val in variable_pairs
        ],
        hidden_variable_count=sum(1 for v, _ in variable_pairs if not v.user_viewable),
    )


async def get_server_runtime(
    db: AsyncSession,
    server_id: int,
    *,
    runtime: InstanceRuntimeAdapter = wings_runtime_adapter,
) -> ServerRuntimeResponse:
    server = await get_server_or_404(db, server_id)
    data = await runtime.get_server(db, int(server.node_id), server.uuid)
    return ServerRuntimeResponse(
        state=str(data.get("state") or "offline"),
        is_suspended=bool(data.get("is_suspended", server.is_suspended)),
        resources=data.get("utilization") or data.get("resources") or {},
        raw=data,
    )


async def list_available_allocations(db: AsyncSession, server_id: int) -> list[ServerAllocationSummary]:
    server = await get_server_or_404(db, server_id)
    rows = await db.execute(
        select(Allocation)
        .where(Allocation.node_id == server.node_id, is_allocation_free_clause())
        .order_by(Allocation.ip.asc(), Allocation.port.asc())
    )
    return [
        ServerAllocationSummary(
            id=int(a.id),
            node_id=int(a.node_id),
            ip=a.ip,
            ip_alias=a.ip_alias,
            port=int(a.port),
            notes=a.notes,
            is_primary=False,
        )
        for a in rows.scalars().all()
    ]


__all__ = [
    "get_server_or_404",
    "get_server_detail",
    "get_server_runtime",
    "list_available_allocations",
]
