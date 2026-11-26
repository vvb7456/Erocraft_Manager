"""Business logic for Location & Node administration."""

from __future__ import annotations

import ipaddress
import uuid as _uuid
from typing import Any
from urllib.parse import urlparse

import yaml
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.node_crypto import decrypt_node_token, encrypt_node_token
from app.core.time import to_iso_z, utc_naive_now_sec
from app.db.models.billing import BillingOrder, BillingPlan
from app.db.models.manager import ManagerHost
from app.db.models.pterodactyl import Location, Mount, PanelNode, PteroServer, mount_node
from app.schemas.admin_nodes_locations import (
    LocationCreateIn,
    LocationOut,
    LocationUpdateIn,
    NodeConfigurationOut,
    NodeCreateIn,
    NodeLocationBrief,
    NodeOut,
)
from app.services import wings_config
from app.services.email import SiteUrlNotConfiguredError, get_site_url
from app.services.wings import wings_service


class AdminResourceError(Exception):
    """Domain error with explicit HTTP status code for routers."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------


async def list_locations(db: AsyncSession) -> list[LocationOut]:
    locations = (
        await db.execute(select(Location).order_by(Location.id.asc()))
    ).scalars().all()
    if not locations:
        return []

    node_counts_rows = (
        await db.execute(
            select(PanelNode.location_id, func.count(PanelNode.id))
            .group_by(PanelNode.location_id)
        )
    ).all()
    node_counts = {int(r[0]): int(r[1]) for r in node_counts_rows}

    server_counts_rows = (
        await db.execute(
            select(PanelNode.location_id, func.count(PteroServer.id))
            .join(PteroServer, PteroServer.node_id == PanelNode.id)
            .group_by(PanelNode.location_id)
        )
    ).all()
    server_counts = {int(r[0]): int(r[1]) for r in server_counts_rows}

    return [
        LocationOut(
            id=loc.id,
            short=loc.short,
            long=loc.long,
            nodes_count=node_counts.get(loc.id, 0),
            servers_count=server_counts.get(loc.id, 0),
            created_at=to_iso_z(loc.created_at),
            updated_at=to_iso_z(loc.updated_at),
        )
        for loc in locations
    ]


async def get_location_out(db: AsyncSession, location_id: int) -> LocationOut | None:
    loc = await db.get(Location, location_id)
    if loc is None:
        return None
    nodes_count = int(
        (
            await db.execute(
                select(func.count(PanelNode.id)).where(PanelNode.location_id == loc.id)
            )
        ).scalar_one()
    )
    servers_count = int(
        (
            await db.execute(
                select(func.count(PteroServer.id))
                .join(PanelNode, PteroServer.node_id == PanelNode.id)
                .where(PanelNode.location_id == loc.id)
            )
        ).scalar_one()
    )
    return LocationOut(
        id=loc.id,
        short=loc.short,
        long=loc.long,
        nodes_count=nodes_count,
        servers_count=servers_count,
        created_at=to_iso_z(loc.created_at),
        updated_at=to_iso_z(loc.updated_at),
    )


async def create_location(db: AsyncSession, payload: LocationCreateIn) -> LocationOut:
    dup = (
        await db.execute(select(Location.id).where(Location.short == payload.short))
    ).scalar_one_or_none()
    if dup is not None:
        raise AdminResourceError(409, f"地域简码 '{payload.short}' 已存在")

    now = utc_naive_now_sec()
    loc = Location(
        short=payload.short,
        long=payload.long,
        created_at=now,
        updated_at=now,
    )
    db.add(loc)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AdminResourceError(409, f"地域简码 '{payload.short}' 已存在") from exc
    await db.refresh(loc)
    return LocationOut(
        id=loc.id,
        short=loc.short,
        long=loc.long,
        nodes_count=0,
        servers_count=0,
        created_at=to_iso_z(loc.created_at),
        updated_at=to_iso_z(loc.updated_at),
    )


async def update_location(
    db: AsyncSession,
    location_id: int,
    payload: LocationUpdateIn,
) -> LocationOut:
    loc = await db.get(Location, location_id)
    if loc is None:
        raise AdminResourceError(404, f"地域 {location_id} 不存在")

    if "short" in payload.model_fields_set and payload.short is not None:
        dup = (
            await db.execute(
                select(Location.id).where(
                    Location.short == payload.short,
                    Location.id != location_id,
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise AdminResourceError(409, f"地域简码 '{payload.short}' 已存在")
        loc.short = payload.short

    if "long" in payload.model_fields_set:
        loc.long = payload.long

    loc.updated_at = utc_naive_now_sec()
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AdminResourceError(409, "地域简码已存在") from exc

    out = await get_location_out(db, location_id)
    assert out is not None
    return out


async def delete_location(db: AsyncSession, location_id: int) -> Location:
    loc = await db.get(Location, location_id)
    if loc is None:
        raise AdminResourceError(404, f"地域 {location_id} 不存在")

    nodes_count = int(
        (
            await db.execute(
                select(func.count(PanelNode.id)).where(PanelNode.location_id == location_id)
            )
        ).scalar_one()
    )
    if nodes_count > 0:
        raise AdminResourceError(
            409,
            f"地域 '{loc.short}' 下仍有 {nodes_count} 个关联节点，无法删除",
        )

    snapshot = Location(id=loc.id, short=loc.short, long=loc.long)
    await db.delete(loc)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AdminResourceError(409, f"地域 '{loc.short}' 存在关联节点，无法删除") from exc
    return snapshot


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


async def list_nodes(db: AsyncSession) -> list[NodeOut]:
    nodes = (
        await db.execute(select(PanelNode).order_by(PanelNode.id.asc()))
    ).scalars().all()
    if not nodes:
        return []

    loc_ids = {n.location_id for n in nodes}
    locs = (
        await db.execute(select(Location).where(Location.id.in_(loc_ids)))
    ).scalars().all()
    loc_map = {loc.id: loc for loc in locs}

    server_counts = {
        int(r[0]): int(r[1])
        for r in (
            await db.execute(
                select(PteroServer.node_id, func.count(PteroServer.id)).group_by(
                    PteroServer.node_id
                )
            )
        ).all()
    }
    plan_counts = {
        int(r[0]): int(r[1])
        for r in (
            await db.execute(
                select(BillingPlan.node_id, func.count(BillingPlan.id)).group_by(
                    BillingPlan.node_id
                )
            )
        ).all()
    }
    host_rows = (
        await db.execute(
            select(ManagerHost.pterodactyl_node_id, ManagerHost.id, ManagerHost.name).where(
                ManagerHost.pterodactyl_node_id.isnot(None)
            )
        )
    ).all()
    host_map = {int(r[0]): (int(r[1]), str(r[2])) for r in host_rows}

    result: list[NodeOut] = []
    for n in nodes:
        loc = loc_map.get(n.location_id)
        host_info = host_map.get(n.id)
        result.append(
            NodeOut(
                id=n.id,
                uuid=n.uuid,
                public=bool(n.public),
                name=n.name,
                description=n.description,
                location_id=n.location_id,
                location=(
                    NodeLocationBrief(id=loc.id, short=loc.short, long=loc.long)
                    if loc is not None
                    else None
                ),
                fqdn=n.fqdn,
                scheme=n.scheme,
                behind_proxy=bool(n.behind_proxy),
                maintenance_mode=bool(n.maintenance_mode),
                memory=n.memory,
                memory_overallocate=n.memory_overallocate,
                disk=n.disk,
                disk_overallocate=n.disk_overallocate,
                upload_size=n.upload_size,
                daemon_token_id=n.daemon_token_id,
                daemon_listen=n.daemon_listen,
                daemon_sftp=n.daemon_sftp,
                daemon_base=n.daemon_base,
                servers_count=server_counts.get(n.id, 0),
                plans_count=plan_counts.get(n.id, 0),
                host_id=host_info[0] if host_info else None,
                host_name=host_info[1] if host_info else None,
                created_at=to_iso_z(n.created_at),
                updated_at=to_iso_z(n.updated_at),
            )
        )
    return result


async def create_node(db: AsyncSession, payload: NodeCreateIn) -> NodeOut:
    loc = await db.get(Location, payload.location_id)
    if loc is None:
        raise AdminResourceError(422, f"地域 location_id={payload.location_id} 不存在")

    token_id, token_plain = wings_config._generate_token()
    encrypted_token = encrypt_node_token(token_plain)
    now = utc_naive_now_sec()
    node = PanelNode(
        uuid=str(_uuid.uuid4()),
        public=1 if payload.public else 0,
        name=payload.name,
        description=payload.description,
        location_id=payload.location_id,
        fqdn=payload.fqdn,
        scheme=payload.scheme,
        behind_proxy=payload.behind_proxy,
        maintenance_mode=payload.maintenance_mode,
        memory=payload.memory,
        memory_overallocate=payload.memory_overallocate,
        disk=payload.disk,
        disk_overallocate=payload.disk_overallocate,
        upload_size=payload.upload_size,
        daemon_token_id=token_id,
        daemon_token=encrypted_token,
        daemon_listen=payload.daemon_listen,
        daemon_sftp=payload.daemon_sftp,
        daemon_base=payload.daemon_base,
        created_at=now,
        updated_at=now,
    )
    db.add(node)
    await db.commit()
    await db.refresh(node)
    wings_service.clear_cache()

    return NodeOut(
        id=node.id,
        uuid=node.uuid,
        public=bool(node.public),
        name=node.name,
        description=node.description,
        location_id=node.location_id,
        location=NodeLocationBrief(id=loc.id, short=loc.short, long=loc.long),
        fqdn=node.fqdn,
        scheme=node.scheme,
        behind_proxy=bool(node.behind_proxy),
        maintenance_mode=bool(node.maintenance_mode),
        memory=node.memory,
        memory_overallocate=node.memory_overallocate,
        disk=node.disk,
        disk_overallocate=node.disk_overallocate,
        upload_size=node.upload_size,
        daemon_token_id=node.daemon_token_id,
        daemon_listen=node.daemon_listen,
        daemon_sftp=node.daemon_sftp,
        daemon_base=node.daemon_base,
        servers_count=0,
        plans_count=0,
        host_id=None,
        host_name=None,
        created_at=to_iso_z(node.created_at),
        updated_at=to_iso_z(node.updated_at),
    )


def _is_private_or_local_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").strip().lower()
    if not host:
        return False
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return False


def _default_port_for_scheme(scheme: str) -> int | None:
    if scheme == "http":
        return 80
    if scheme == "https":
        return 443
    return None


def _parse_origin(url: str) -> tuple[str, str, int | None] | None:
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").strip().lower()
    if scheme not in ("http", "https") or not host:
        return None
    try:
        port = parsed.port if parsed.port is not None else _default_port_for_scheme(scheme)
    except ValueError:
        return None
    return scheme, host, port


def _origins_match_for_wings_warning(fallback_origin: str, remote_url: str) -> bool:
    orig = _parse_origin(fallback_origin)
    rem = _parse_origin(remote_url)
    if orig is None or rem is None:
        return False
    o_scheme, o_host, o_port = orig
    r_scheme, r_host, r_port = rem
    if o_host != r_host:
        return False
    if o_port == r_port:
        return True
    # Behind a TLS-terminating reverse proxy without X-Forwarded-Proto, backend sees
    # http://<domain>(:80) while SITE_URL is https://<domain>(:443).
    if o_scheme == "http" and r_scheme == "https" and o_port == 80 and r_port == 443:
        return True
    return False


async def build_node_configuration(
    db: AsyncSession,
    node_id: int,
    *,
    fallback_origin: str | None = None,
) -> NodeConfigurationOut:
    node = await db.get(PanelNode, node_id)
    if node is None:
        raise AdminResourceError(404, f"节点 {node_id} 不存在")

    warnings: list[str] = []
    try:
        remote_url = await get_site_url(db)
    except SiteUrlNotConfiguredError as exc:
        if fallback_origin and (
            fallback_origin.startswith("http://") or fallback_origin.startswith("https://")
        ):
            remote_url = fallback_origin.rstrip("/")
            warnings.append(
                "系统尚未配置 SITE_URL，已临时使用当前请求地址作为 remote；请在系统设置中配置 SITE_URL。"
            )
        else:
            raise AdminResourceError(
                400,
                "SITE_URL 未配置，无法生成 Wings config.yml 的 remote 地址，请先在系统设置中配置 SITE_URL",
            ) from exc

    if _is_private_or_local_url(remote_url):
        warnings.append(
            "remote 为内网或本机地址：如果浏览器通过公网域名连接 Wings 控制台，请在 config.yml 中补充 allowed_origins。"
        )
    elif fallback_origin and not _origins_match_for_wings_warning(
        fallback_origin, remote_url
    ):
        warnings.append(
            f"当前访问 Origin ({fallback_origin.rstrip('/')}) 与 remote ({remote_url}) 不同，如需跨域访问控制台请将该 Origin 加入 allowed_origins。"
        )

    mount_rows = (
        await db.execute(
            select(Mount.source)
            .join(mount_node, mount_node.c.mount_id == Mount.id)
            .where(mount_node.c.node_id == node.id)
            .order_by(Mount.id.asc())
        )
    ).scalars().all()

    token_plain = decrypt_node_token(node.daemon_token)

    config: dict[str, Any] = {
        "debug": False,
        "uuid": node.uuid,
        "token_id": node.daemon_token_id,
        "token": token_plain,
        "api": {
            "host": "0.0.0.0",
            "port": int(node.daemon_listen),
            "ssl": {
                "enabled": (not bool(node.behind_proxy) and node.scheme == "https"),
                "cert": f"/etc/letsencrypt/live/{node.fqdn.lower()}/fullchain.pem",
                "key": f"/etc/letsencrypt/live/{node.fqdn.lower()}/privkey.pem",
            },
            "upload_limit": int(node.upload_size),
        },
        "system": {
            "data": node.daemon_base,
            "sftp": {
                "bind_port": int(node.daemon_sftp),
            },
        },
        "allowed_mounts": [str(src) for src in mount_rows],
        "remote": remote_url,
    }

    yaml_text = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)

    return NodeConfigurationOut(
        node_id=node.id,
        node_name=node.name,
        remote=remote_url,
        config=config,
        yaml=yaml_text,
        warnings=warnings,
    )


async def delete_node(db: AsyncSession, node_id: int) -> PanelNode:
    node = await db.get(PanelNode, node_id)
    if node is None:
        raise AdminResourceError(404, f"节点 {node_id} 不存在")

    # 1. Existing servers on this node
    servers_count = int(
        (
            await db.execute(
                select(func.count(PteroServer.id)).where(PteroServer.node_id == node_id)
            )
        ).scalar_one()
    )
    if servers_count > 0:
        raise AdminResourceError(
            409,
            f"节点 '{node.name}' 上仍有 {servers_count} 台服务器，无法删除",
        )

    # 2. Billing plans reference nodes.id without a DB FK
    plans_count = int(
        (
            await db.execute(
                select(func.count(BillingPlan.id)).where(BillingPlan.node_id == node_id)
            )
        ).scalar_one()
    )
    if plans_count > 0:
        raise AdminResourceError(
            409,
            f"节点 '{node.name}' 仍被 {plans_count} 个计费套餐引用，请先修改或删除相关套餐",
        )

    # 3. In-flight billing orders reserving this node
    orders_count = int(
        (
            await db.execute(
                select(func.count(BillingOrder.id)).where(
                    BillingOrder.reserved_node_id == node_id,
                    BillingOrder.status.in_(("pending", "processing")),
                )
            )
        ).scalar_one()
    )
    if orders_count > 0:
        raise AdminResourceError(
            409,
            f"节点 '{node.name}' 存在 {orders_count} 笔未完成订单的预留占用，无法删除",
        )

    from app.db.repositories.allocation_reservations import has_active_reservations_on_node

    if await has_active_reservations_on_node(db, node_id):
        raise AdminResourceError(
            409,
            f"节点 '{node.name}' 存在活跃的订单端口预留占用，无法删除",
        )

    # 4. manager_hosts.pterodactyl_node_id has ON DELETE CASCADE — block direct deletion
    # so monitoring, alerts, certificate deployments and tunnels are not silently wiped.
    bound_host = (
        await db.execute(
            select(ManagerHost.id, ManagerHost.name).where(
                ManagerHost.pterodactyl_node_id == node_id
            )
        )
    ).first()
    if bound_host is not None:
        raise AdminResourceError(
            409,
            f"节点 '{node.name}' 已绑定到主机 '{bound_host.name}' (id={bound_host.id})，"
            "为防止级联清空监控/告警/证书/隧道配置，请先删除或解绑该主机",
        )

    snapshot = PanelNode(
        id=node.id,
        uuid=node.uuid,
        name=node.name,
        location_id=node.location_id,
        fqdn=node.fqdn,
        scheme=node.scheme,
        memory=node.memory,
        disk=node.disk,
        daemon_token_id=node.daemon_token_id,
        daemon_token="",
        daemon_listen=node.daemon_listen,
        daemon_sftp=node.daemon_sftp,
        daemon_base=node.daemon_base,
    )
    await db.delete(node)
    await db.commit()
    wings_service.clear_cache()
    return snapshot
