"""Admin resource routes for create-server workflows."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.runtime_settings import SETTINGS_SPECS, defaults_for
from app.core.settings_store import get_settings_store
from app.db.models.pterodactyl import PteroUser
from app.db.repositories.resources import resource_repository
from app.schemas.resources import (
    AllocationsResponse,
    AllocationResource,
    EggResource,
    EggsResponse,
    EggVariableResource,
    EggVariablesResponse,
    NestsResponse,
    NestResource,
    NodesResponse,
    NodeResource,
    ServerDefaultsResponse,
    SimpleUserResource,
    UsersResourceResponse,
)

router = APIRouter(tags=["resources"])


@router.get("/nests", response_model=NestsResponse)
async def list_nests(
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> NestsResponse:
    nests = await resource_repository.list_nests(db)
    return NestsResponse(nests=[NestResource(id=nest.id, name=nest.name) for nest in nests])


@router.get("/nodes", response_model=NodesResponse)
async def list_nodes(
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> NodesResponse:
    nodes = await resource_repository.list_nodes(db)
    return NodesResponse(nodes=[NodeResource(id=node.id, name=node.name) for node in nodes])


@router.get("/resources/users", response_model=UsersResourceResponse)
async def list_users_simple(
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UsersResourceResponse:
    users = await resource_repository.list_users_simple(db)
    return UsersResourceResponse(
        users=[SimpleUserResource(id=user.id, username=user.username, email=user.email) for user in users]
    )


@router.get("/resources/server-defaults", response_model=ServerDefaultsResponse)
async def server_defaults(
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ServerDefaultsResponse:
    store = get_settings_store()
    values = await store.get_many(
        db,
        {
            key: default
            for key, default in defaults_for(SETTINGS_SPECS).items()
            if key.startswith("DEFAULT_") or key in {"DOCKER_IMAGE", "SERVER_NAME_PREFIX"}
        },
    )
    return ServerDefaultsResponse(
        nest_id=int(values["DEFAULT_NEST_ID"]),
        egg_id=int(values["DEFAULT_EGG_ID"]),
        node_id=int(values["DEFAULT_NODE_ID"]),
        docker_image=str(values["DOCKER_IMAGE"]),
        cpu=int(values["DEFAULT_CPU"]),
        memory=int(values["DEFAULT_MEMORY"]),
        disk=int(values["DEFAULT_DISK"]),
        databases=int(values["DEFAULT_DATABASES"]),
        backups=int(values["DEFAULT_BACKUPS"]),
        allocations=int(values["DEFAULT_ALLOCATIONS"]),
        server_name_prefix=str(values["SERVER_NAME_PREFIX"]),
    )


@router.get("/nodes/{node_id}/allocations", response_model=AllocationsResponse)
async def node_allocations(
    node_id: int,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AllocationsResponse:
    allocations = await resource_repository.list_unassigned_allocations(db, node_id)
    return AllocationsResponse(
        allocations=[AllocationResource(id=item.id, ip=item.ip, port=item.port) for item in allocations]
    )


@router.get("/nests/{nest_id}/eggs", response_model=EggsResponse)
async def nest_eggs(
    nest_id: int,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EggsResponse:
    eggs = await resource_repository.list_eggs(db, nest_id)
    return EggsResponse(
        eggs=[
            EggResource(
                id=egg.id,
                name=egg.name,
                docker_image=egg.docker_image,
                startup=egg.startup or "",
            )
            for egg in eggs
        ]
    )


@router.get("/nests/{nest_id}/eggs/{egg_id}/variables", response_model=EggVariablesResponse)
async def egg_variables(
    nest_id: int,
    egg_id: int,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EggVariablesResponse:
    egg = await resource_repository.get_egg(db, egg_id)
    if egg is None or egg.nest_id != nest_id:
        raise HTTPException(status_code=404, detail="Egg not found")

    variables = await resource_repository.list_egg_variables(db, egg_id)
    return EggVariablesResponse(
        variables=[
            EggVariableResource(
                name=variable.name,
                env_variable=variable.env_variable,
                default_value=variable.default_value,
                description=variable.description,
                rules=variable.rules,
            )
            for variable in variables
        ]
    )
