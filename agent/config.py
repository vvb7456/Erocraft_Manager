"""Agent V2 configuration loader.

agent.yaml schema:

    manager:
      url: https://manager.example.com   # 信息性，运行时不主动调用
      node_id: 9                         # 可选；仅 Wings/Pterodactyl 兼容信息

    agent:
      role: wings_node                   # wings_node | generic_host | synology_dsm
      bind: "0.0.0.0:48765"
      token: "<node-specific bearer token>"
      allow_ips: ["203.0.113.7"]         # 可选；空 = 不限制

    wings:                               # 仅 role=wings_node 时读取
      config_path: /etc/pterodactyl/config.yml
      service_name: wings

    collect:
      cache_ttl_sec: 5

    probes:
      - name: clash_proxy
        type: http
        target: http://127.0.0.1:7890
        timeout: 5
      - name: pve_host
        type: tcp
        target: 10.0.0.1:22
        timeout: 5
        tls_verify: true

    cert_install_targets:
      - name: nginx_main
        type: file                         # file | synology_dsm
        cert_path: /etc/nginx/ssl/example/fullchain.pem
        key_path: /etc/nginx/ssl/example/privkey.pem
        reload_cmd: systemctl reload nginx
      - name: dsm_default
        type: synology_dsm
        synology:
          certificate_desc: erocraft.com
          create_if_missing: false
          as_default: true

    logging:
      level: INFO
"""

from __future__ import annotations

import os
import secrets
from typing import List, Literal, Optional, Union
from typing_extensions import Annotated

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

AgentRole = Literal["wings_node", "generic_host", "synology_dsm"]
_AGENT_TOKEN_BYTES = 32


def _generate_agent_token() -> str:
    return secrets.token_urlsafe(_AGENT_TOKEN_BYTES)


def bootstrap_agent_token(path: str | Path) -> Optional[str]:
    """Ensure ``agent.token`` exists in config file.

    If token is missing/empty, generate one, write it back to disk, and return
    the plaintext token so startup logs can display it once for operator copy.
    """
    p = Path(path)
    try:
        mode = p.stat().st_mode & 0o777
    except OSError:
        mode = 0o600

    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raw = {}

    agent_raw = raw.get("agent")
    if not isinstance(agent_raw, dict):
        agent_raw = {}
        raw["agent"] = agent_raw

    current = agent_raw.get("token")
    if isinstance(current, str) and current.strip():
        return None

    token = _generate_agent_token()
    agent_raw["token"] = token

    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, sort_keys=False, allow_unicode=False)
    os.chmod(tmp, mode)
    os.replace(tmp, p)
    return token


class ManagerSection(BaseModel):
    # Reserved for a future Push / registration mode where the agent calls
    # back to Manager. Phase-1 is strictly Pull (Manager -> Agent via
    # /v1/metrics), so url is never read by the agent at runtime.
    url: Optional[str] = None
    # Legacy compatibility field for Wings/Pterodactyl nodes. Non-Wings hosts
    # are addressed by manager_hosts.id on the Manager side and should omit it.
    node_id: Optional[int] = None


class AgentSection(BaseModel):
    role: AgentRole = "wings_node"
    bind: str = "0.0.0.0:48765"
    token: str
    allow_ips: List[str] = Field(default_factory=list)

    @field_validator("bind")
    @classmethod
    def _validate_bind(cls, v: str) -> str:
        parts = v.rsplit(":", 1)
        if len(parts) != 2:
            raise ValueError("bind must be in host:port format")
        try:
            int(parts[1])
        except ValueError:
            raise ValueError(f"invalid port in bind: {parts[1]}")
        return v

    @property
    def host(self) -> str:
        return self.bind.rsplit(":", 1)[0]

    @property
    def port(self) -> int:
        return int(self.bind.rsplit(":", 1)[1])

    @property
    def is_wings(self) -> bool:
        return self.role == "wings_node"


class WingsSection(BaseModel):
    config_path: str = "/etc/pterodactyl/config.yml"
    service_name: str = "wings"


class CollectSection(BaseModel):
    cache_ttl_sec: int = 5


class ProbeConfig(BaseModel):
    name: str
    type: Literal["http", "tcp"]
    target: str
    timeout: float = 5.0
    tls_verify: bool = True
    proxy: Optional[str] = None


# ---- Certificate install targets (discriminated union) ----

class SynologyTarget(BaseModel):
    certificate_desc: str
    create_if_missing: bool = False
    as_default: bool = True


class CertInstallTargetFile(BaseModel):
    name: str
    type: Literal["file"] = "file"
    cert_path: str
    key_path: str
    reload_cmd: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _required_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v


class CertInstallTargetDSM(BaseModel):
    name: str
    type: Literal["synology_dsm"] = "synology_dsm"
    synology: SynologyTarget

    @field_validator("name")
    @classmethod
    def _required_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v


CertInstallTarget = Annotated[
    Union[CertInstallTargetFile, CertInstallTargetDSM],
    Field(discriminator="type"),
]


class LoggingSection(BaseModel):
    level: str = "INFO"


class AgentConfig(BaseModel):
    model_config = {"extra": "forbid"}

    manager: ManagerSection = Field(default_factory=ManagerSection)
    agent: AgentSection
    wings: WingsSection = Field(default_factory=WingsSection)
    collect: CollectSection = Field(default_factory=CollectSection)
    probes: List[ProbeConfig] = Field(default_factory=list)
    cert_install_targets: List[CertInstallTarget] = Field(default_factory=list)
    logging: LoggingSection = Field(default_factory=LoggingSection)

    @field_validator("cert_install_targets", mode="before")
    @classmethod
    def _default_cert_targets(cls, value: object) -> object:
        return [] if value is None else value


def load_config(path: str | Path) -> AgentConfig:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return AgentConfig.model_validate(raw)
