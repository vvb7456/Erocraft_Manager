"""Schemas for admin resource routes."""

from __future__ import annotations

from pydantic import BaseModel


class SimpleUserResource(BaseModel):
    id: int
    username: str
    email: str


class UsersResourceResponse(BaseModel):
    users: list[SimpleUserResource]


class NestResource(BaseModel):
    id: int
    name: str


class NestsResponse(BaseModel):
    nests: list[NestResource]


class NodeResource(BaseModel):
    id: int
    name: str


class NodesResponse(BaseModel):
    nodes: list[NodeResource]


class AllocationResource(BaseModel):
    id: int
    ip: str
    port: int


class AllocationsResponse(BaseModel):
    allocations: list[AllocationResource]


class EggResource(BaseModel):
    id: int
    name: str
    docker_image: str
    startup: str


class EggsResponse(BaseModel):
    eggs: list[EggResource]


class EggVariableResource(BaseModel):
    name: str
    env_variable: str
    default_value: str
    description: str
    rules: str | None


class EggVariablesResponse(BaseModel):
    variables: list[EggVariableResource]


class ServerDefaultsResponse(BaseModel):
    nest_id: int
    egg_id: int
    node_id: int
    docker_image: str
    cpu: int
    memory: int
    disk: int
    databases: int
    backups: int
    allocations: int
    server_name_prefix: str
