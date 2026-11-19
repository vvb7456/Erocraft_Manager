"""Wings remote server configuration assembly engine.

Mirrors Pterodactyl Panel's ``ServerConfigurationStructureService``,
``EnvironmentService``, and ``EggConfigurationService`` with batch preloading
to prevent N+1 queries on ``GET /api/remote/servers``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.wings_remote_auth import WingsRemoteError
from app.db.models.pterodactyl import (
    Allocation,
    Egg,
    EggVariable,
    Location,
    Mount,
    PanelNode,
    PteroServer,
    ServerVariable,
    mount_server,
)

_PLACEHOLDER_RE = re.compile(r"\{\{([\w.-]*)\}\}")

_LEGACY_MODIFIER_MAP: dict[str, str] = {
    "config.docker.interface": "config.docker.network.interface",
    "server.build.env.SERVER_MEMORY": "server.build.memory",
    "env.SERVER_MEMORY": "server.build.memory",
    "server.build.env.SERVER_IP": "server.build.default.ip",
    "env.SERVER_IP": "server.build.default.ip",
    "server.build.env.SERVER_PORT": "server.build.default.port",
    "env.SERVER_PORT": "server.build.default.port",
}


def _dot_get(mapping: dict[str, Any], path: str, default: Any = "") -> Any:
    if path in mapping:
        return mapping[path]
    current: Any = mapping
    for segment in path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return default
    return current


def _php_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else ""
    return str(value)


def _replace_legacy_modifiers(key: str, value: str) -> str:
    replacement = _LEGACY_MODIFIER_MAP.get(key, key)
    return value.replace(f"{{{{{key}}}}}", f"{{{{{replacement}}}}}")


def _match_and_replace_keys(value: Any, structure: dict[str, Any]) -> Any:
    # Preserve non-string JSON scalars (bool/int/float/null) verbatim for Wings parsers.
    if not isinstance(value, str):
        return value

    for key in _PLACEHOLDER_RE.findall(value):
        if not key.startswith(("server.", "env.", "config.")):
            continue

        # Matches EggConfigurationService.php: replaceLegacyModifiers rewrites $value
        # without updating $key in the same loop iteration.
        value = _replace_legacy_modifiers(key, value)

        if key.startswith("config."):
            continue

        if key.startswith("server."):
            plucked = _dot_get(structure, key[len("server.") :], "")
            value = value.replace(f"{{{{{key}}}}}", _php_str(plucked))
            continue

        plucked = _dot_get(structure, "build.env." + key[len("env.") :], "")
        value = value.replace(f"{{{{{key}}}}}", _php_str(plucked))

    return value


def _iterate_find(data: Any, structure: dict[str, Any]) -> Any:
    if isinstance(data, dict):
        return {k: _iterate_find(v, structure) for k, v in data.items()}
    if isinstance(data, list):
        return [_iterate_find(v, structure) for v in data]
    return _match_and_replace_keys(data, structure)


def convert_startup(raw_config_startup: str | None) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    if raw_config_startup:
        try:
            loaded = json.loads(raw_config_startup)
            if isinstance(loaded, dict):
                parsed = loaded
        except json.JSONDecodeError:
            parsed = {}

    done = parsed.get("done")
    if isinstance(done, str):
        done = [done]

    strip_ansi = parsed.get("strip_ansi")
    if strip_ansi is None:
        strip_ansi = False

    return {
        "done": done,
        "user_interaction": [],
        "strip_ansi": strip_ansi,
    }


def convert_stop(stop: str | None) -> dict[str, str]:
    raw = stop or ""
    if not raw.startswith("^"):
        return {
            "type": "command",
            "value": raw,
        }
    return {
        "type": "signal",
        "value": raw[1:].upper(),
    }


def replace_config_placeholders(
    legacy_structure: dict[str, Any],
    raw_config_files: str | None,
) -> list[dict[str, Any]]:
    if not raw_config_files:
        return []
    try:
        configs = json.loads(raw_config_files)
    except json.JSONDecodeError:
        return []
    if not isinstance(configs, dict):
        return []

    response: list[dict[str, Any]] = []
    for file_path, data in configs.items():
        if not isinstance(data, dict) or data.get("find") is None:
            continue

        entry: dict[str, Any] = {k: v for k, v in data.items() if k != "find"}
        entry["file"] = file_path
        replacements: list[dict[str, Any]] = []

        iterated = _iterate_find(data["find"], legacy_structure)
        if isinstance(iterated, dict):
            for find_key, replace_val in iterated.items():
                if isinstance(replace_val, dict):
                    for if_val, replace_with in replace_val.items():
                        replacements.append(
                            {
                                "match": find_key,
                                "if_value": if_val,
                                "replace_with": replace_with,
                            }
                        )
                else:
                    replacements.append(
                        {
                            "match": find_key,
                            "replace_with": replace_val,
                        }
                    )

        entry["replace"] = replacements
        response.append(entry)

    return response


def build_environment(
    server: PteroServer,
    egg_vars: list[EggVariable],
    server_var_values: dict[int, str | None],
    location_short: str | None,
) -> dict[str, Any]:
    env: dict[str, Any] = {}
    for var in egg_vars:
        sv = server_var_values.get(var.id)
        # Empty string "" is a deliberate override and must not fall back to default_value.
        env[var.env_variable] = sv if sv is not None else var.default_value

    env["STARTUP"] = server.startup
    env["P_SERVER_LOCATION"] = location_short
    env["P_SERVER_UUID"] = server.uuid
    env["P_SERVER_ALLOCATION_LIMIT"] = server.allocation_limit
    return env


def _build_allocation_mappings(
    allocs: list[Allocation],
    *,
    node_id: int | None = None,
) -> dict[str, list[int]]:
    mappings: dict[str, list[int]] = {}
    for alloc in allocs:
        if node_id is not None and alloc.node_id != node_id:
            continue
        mappings.setdefault(alloc.ip, []).append(int(alloc.port))
    return mappings


def build_server_settings(
    server: PteroServer,
    *,
    egg: Egg,
    parent_egg: Egg | None,
    default_alloc: Allocation,
    server_allocs: list[Allocation],
    server_mounts: list[Mount],
    environment: dict[str, Any],
) -> dict[str, Any]:
    return {
        "uuid": server.uuid,
        "meta": {
            "name": server.name,
            "description": server.description or "",
        },
        "suspended": server.status == "suspended",
        "environment": environment,
        "invocation": server.startup,
        "skip_egg_scripts": bool(server.skip_scripts),
        "build": {
            "memory_limit": int(server.memory),
            "swap": int(server.swap),
            "io_weight": int(server.io),
            "cpu_limit": int(server.cpu),
            "threads": server.threads,
            "disk_space": int(server.disk),
            "oom_disabled": bool(server.oom_disabled),
        },
        "container": {
            "image": server.image,
            "oom_disabled": bool(server.oom_disabled),
            "requires_rebuild": False,
        },
        "allocations": {
            "force_outgoing_ip": bool(egg.force_outgoing_ip),
            "default": {
                "ip": default_alloc.ip,
                "port": int(default_alloc.port),
            },
            "mappings": _build_allocation_mappings(server_allocs, node_id=server.node_id),
        },
        "mounts": [
            {
                "source": mount.source,
                "target": mount.target,
                "read_only": bool(mount.read_only),
            }
            for mount in server_mounts
        ],
        "egg": {
            "id": egg.uuid,
            "file_denylist": egg.resolve_file_denylist(parent_egg),
        },
    }


def build_legacy_structure(
    server: PteroServer,
    *,
    egg: Egg,
    default_alloc: Allocation,
    server_allocs: list[Allocation],
    environment: dict[str, Any],
) -> dict[str, Any]:
    return {
        "uuid": server.uuid,
        "build": {
            "default": {
                "ip": default_alloc.ip,
                "port": int(default_alloc.port),
            },
            "ports": _build_allocation_mappings(server_allocs),
            "env": environment,
            "oom_disabled": bool(server.oom_disabled),
            "memory": int(server.memory),
            "swap": int(server.swap),
            "io": int(server.io),
            "cpu": int(server.cpu),
            "threads": server.threads,
            "disk": int(server.disk),
            "image": server.image,
        },
        "service": {
            "egg": egg.uuid,
            "skip_scripts": bool(server.skip_scripts),
        },
        "rebuild": False,
        "suspended": 1 if server.status == "suspended" else 0,
    }


def build_process_configuration(
    legacy_structure: dict[str, Any],
    *,
    egg: Egg,
    parent_egg: Egg | None,
) -> dict[str, Any]:
    return {
        "startup": convert_startup(egg.resolve_config_startup(parent_egg)),
        "stop": convert_stop(egg.resolve_config_stop(parent_egg)),
        "configs": replace_config_placeholders(
            legacy_structure,
            egg.resolve_config_files(parent_egg),
        ),
    }


async def build_server_configs_batch(
    db: AsyncSession,
    servers: list[PteroServer],
    *,
    include_top_uuid: bool,
) -> list[dict[str, Any]]:
    if not servers:
        return []

    server_ids = [s.id for s in servers]
    node_ids = {s.node_id for s in servers}
    egg_ids = {s.egg_id for s in servers}
    default_alloc_ids = {s.allocation_id for s in servers}

    nodes = (
        await db.execute(select(PanelNode).where(PanelNode.id.in_(node_ids)))
    ).scalars().all()
    nodes_by_id = {n.id: n for n in nodes}

    location_ids = {n.location_id for n in nodes}
    locations_by_id: dict[int, Location] = {}
    if location_ids:
        locations = (
            await db.execute(select(Location).where(Location.id.in_(location_ids)))
        ).scalars().all()
        locations_by_id = {loc.id: loc for loc in locations}

    allocations = (
        await db.execute(
            select(Allocation)
            .where(
                or_(
                    Allocation.server_id.in_(server_ids),
                    Allocation.id.in_(default_alloc_ids),
                )
            )
            .order_by(Allocation.id.asc())
        )
    ).scalars().all()
    alloc_by_id = {a.id: a for a in allocations}
    allocs_by_server: dict[int, list[Allocation]] = {}
    for alloc in allocations:
        if alloc.server_id is not None:
            allocs_by_server.setdefault(alloc.server_id, []).append(alloc)

    eggs = (
        await db.execute(select(Egg).where(Egg.id.in_(egg_ids)))
    ).scalars().all()
    eggs_by_id = {e.id: e for e in eggs}

    parent_egg_ids = {
        e.config_from
        for e in eggs
        if e.config_from is not None and e.config_from not in eggs_by_id
    }
    if parent_egg_ids:
        parent_eggs = (
            await db.execute(select(Egg).where(Egg.id.in_(parent_egg_ids)))
        ).scalars().all()
        for parent in parent_eggs:
            eggs_by_id[parent.id] = parent

    egg_vars = (
        await db.execute(
            select(EggVariable)
            .where(EggVariable.egg_id.in_(egg_ids))
            .order_by(EggVariable.id.asc())
        )
    ).scalars().all()
    egg_vars_by_egg: dict[int, list[EggVariable]] = {}
    for var in egg_vars:
        egg_vars_by_egg.setdefault(var.egg_id, []).append(var)

    server_vars = (
        await db.execute(
            select(ServerVariable).where(ServerVariable.server_id.in_(server_ids))
        )
    ).scalars().all()
    server_vars_by_server: dict[int, dict[int, str | None]] = {}
    for sv in server_vars:
        server_vars_by_server.setdefault(sv.server_id, {})[sv.variable_id] = sv.variable_value

    mount_rows = (
        await db.execute(
            select(mount_server.c.server_id, Mount)
            .join(Mount, Mount.id == mount_server.c.mount_id)
            .where(mount_server.c.server_id.in_(server_ids))
            .order_by(Mount.id.asc())
        )
    ).all()
    mounts_by_server: dict[int, list[Mount]] = {}
    for sid, mount in mount_rows:
        mounts_by_server.setdefault(int(sid), []).append(mount)

    results: list[dict[str, Any]] = []
    for server in servers:
        egg = eggs_by_id.get(server.egg_id)
        if egg is None:
            raise WingsRemoteError(
                500,
                "HttpException",
                f"Egg {server.egg_id} missing for server {server.uuid}.",
            )
        parent_egg = eggs_by_id.get(egg.config_from) if egg.config_from is not None else None

        default_alloc = alloc_by_id.get(server.allocation_id)
        if default_alloc is None:
            raise WingsRemoteError(
                500,
                "HttpException",
                f"Default allocation {server.allocation_id} missing for server {server.uuid}.",
            )

        node = nodes_by_id.get(server.node_id)
        location = locations_by_id.get(node.location_id) if node is not None else None
        location_short = location.short if location is not None else None

        server_allocs = allocs_by_server.get(server.id, [])
        server_mounts = mounts_by_server.get(server.id, [])
        environment = build_environment(
            server,
            egg_vars_by_egg.get(server.egg_id, []),
            server_vars_by_server.get(server.id, {}),
            location_short,
        )

        settings = build_server_settings(
            server,
            egg=egg,
            parent_egg=parent_egg,
            default_alloc=default_alloc,
            server_allocs=server_allocs,
            server_mounts=server_mounts,
            environment=environment,
        )
        legacy = build_legacy_structure(
            server,
            egg=egg,
            default_alloc=default_alloc,
            server_allocs=server_allocs,
            environment=environment,
        )
        process_configuration = build_process_configuration(
            legacy,
            egg=egg,
            parent_egg=parent_egg,
        )

        if include_top_uuid:
            results.append(
                {
                    "uuid": server.uuid,
                    "settings": settings,
                    "process_configuration": process_configuration,
                }
            )
        else:
            results.append(
                {
                    "settings": settings,
                    "process_configuration": process_configuration,
                }
            )

    return results
