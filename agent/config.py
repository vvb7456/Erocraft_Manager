"""Agent V2 configuration loader.

agent.yaml schema:

    manager:
      url: https://manager.example.com   # 信息性，运行时不主动调用
      node_id: 9

    agent:
      bind: "0.0.0.0:48765"
      token: "<node-specific bearer token>"
      allow_ips: ["203.0.113.7"]         # 可选；空 = 不限制

    wings:
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

    logging:
      level: INFO
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class ManagerSection(BaseModel):
    # Reserved for a future Push / registration mode where the agent calls
    # back to Manager. Phase-1 is strictly Pull (Manager -> Agent via
    # /v1/metrics), so this field is never read by the agent at runtime.
    # Safe to omit from new agent.yaml files; existing deployments that set
    # it are accepted and ignored. See Phase-1 CR §4.7.
    url: str | None = None
    node_id: int


class AgentSection(BaseModel):
    bind: str = "0.0.0.0:48765"
    token: str
    allow_ips: list[str] = Field(default_factory=list)

    @property
    def host(self) -> str:
        return self.bind.split(":", 1)[0]

    @property
    def port(self) -> int:
        return int(self.bind.split(":", 1)[1])


class WingsSection(BaseModel):
    config_path: str = "/etc/pterodactyl/config.yml"
    service_name: str = "wings"


class CollectSection(BaseModel):
    cache_ttl_sec: int = 5


class ProbeConfig(BaseModel):
    name: str
    type: str  # "http" | "tcp"
    target: str
    timeout: float = 5.0
    tls_verify: bool = True
    # Optional outbound proxy for HTTP probes — e.g. "http://10.0.0.254:7890"
    # or "socks5://10.0.0.254:7891". When set, the probe checks end-to-end
    # reachability *through* that proxy (latency = full round-trip).
    # Ignored by TCP probe. SOCKS requires ``httpx[socks]``.
    proxy: str | None = None

    @field_validator("type")
    @classmethod
    def _check_type(cls, v: str) -> str:
        if v not in ("http", "tcp"):
            raise ValueError(f"unsupported probe type: {v}")
        return v


class LoggingSection(BaseModel):
    level: str = "INFO"


class AgentConfig(BaseModel):
    manager: ManagerSection
    agent: AgentSection
    wings: WingsSection = Field(default_factory=WingsSection)
    collect: CollectSection = Field(default_factory=CollectSection)
    probes: list[ProbeConfig] = Field(default_factory=list)
    logging: LoggingSection = Field(default_factory=LoggingSection)


def load_config(path: str | Path) -> AgentConfig:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return AgentConfig.model_validate(raw)
