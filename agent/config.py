"""Agent V2 configuration loader.

agent.yaml schema:

    manager:
      node_id: 9                         # 可选；仅 Wings/Pterodactyl 兼容信息

    agent:
      role: wings_node                   # wings_node | generic_host
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
        cert_path: /etc/nginx/ssl/example/fullchain.pem
        key_path: /etc/nginx/ssl/example/privkey.pem
        reload_cmd: systemctl reload nginx

    logging:
      level: INFO
"""

from __future__ import annotations

import secrets
from typing import Literal

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from .utils.atomic import atomic_write_text

AgentRole = Literal["wings_node", "generic_host"]
_AGENT_TOKEN_BYTES = 32
#: Mode forced on any config file we've written a token into. The token is a
#: bearer credential — keep it owner-read-only regardless of the user's umask
#: or the source file's permissions (SSH / GPG / systemd-creds all do this).
_CONFIG_SECRET_MODE = 0o600


def _generate_agent_token() -> str:
    return secrets.token_urlsafe(_AGENT_TOKEN_BYTES)


def _replace_token_in_yaml_text(text: str, new_token: str) -> str:
    """Surgically replace the value of ``token:`` under the top-level
    ``agent:`` block.

    Preserves every other line verbatim — comments, ordering, indentation,
    other fields, blank lines — because operators hand-edit this file and
    a full ``yaml.safe_dump`` round-trip would silently delete their
    annotations. Only the matched ``token:`` line is rewritten.

    Raises :class:`ValueError` if no ``token:`` line is found directly under
    the ``agent:`` block. Pydantic validation requires ``agent.token`` so
    operators always have a line to seed (even if its value is empty).
    """
    lines = text.splitlines(keepends=True)
    in_agent = False
    block_indent: int | None = None

    for i, line in enumerate(lines):
        stripped_newline = line.rstrip("\r\n")
        if not stripped_newline.strip():
            continue
        leading = len(stripped_newline) - len(stripped_newline.lstrip())
        content = stripped_newline.lstrip()

        # Top-level key — switch contexts. Comments at column 0 don't count.
        if leading == 0:
            if content.startswith("#"):
                continue
            key = content.split(":", 1)[0].strip()
            in_agent = key == "agent"
            block_indent = None
            continue

        if not in_agent or content.startswith("#"):
            continue

        # First indented line under `agent:` establishes the child indent.
        if block_indent is None:
            block_indent = leading
        if leading != block_indent:
            continue

        key = content.split(":", 1)[0].strip()
        if key != "token":
            continue

        # Preserve trailing line comment, if any. Our generated token is
        # base64url (no ``#``), so a naive partition is safe for our value.
        after_colon = content.split(":", 1)[1] if ":" in content else ""
        comment_suffix = ""
        if "#" in after_colon:
            _, _, comment_part = after_colon.partition("#")
            comment_suffix = "  #" + comment_part

        if line.endswith("\r\n"):
            newline = "\r\n"
        elif line.endswith("\n"):
            newline = "\n"
        else:
            newline = ""

        lines[i] = f'{" " * leading}token: "{new_token}"{comment_suffix}{newline}'
        return "".join(lines)

    raise ValueError("agent.token line not found in config file")


def bootstrap_agent_token(path: str | Path) -> str | None:
    """Ensure ``agent.token`` exists in the config file.

    If the token is missing/empty, generate one and write it back **without
    rewriting the rest of the YAML** (preserves comments and field order).
    After writing, the file mode is forced to ``0o600`` because it now
    contains a bearer credential.

    Returns the plaintext token if one was generated (so startup logs can
    display it once for operator copy), or ``None`` if a token was already
    present.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")

    # Parse once to decide whether bootstrap is needed; safe_load tolerates
    # ``token:`` / ``token: ""`` / missing key all as falsy.
    parsed = yaml.safe_load(text) or {}
    agent_raw = parsed.get("agent") if isinstance(parsed, dict) else None
    if isinstance(agent_raw, dict):
        current = agent_raw.get("token")
        if isinstance(current, str) and current.strip():
            # Token already set; still tighten mode in case the file was
            # created world-readable (common after `cp` with default umask).
            _enforce_secret_mode(p)
            return None

    token = _generate_agent_token()
    updated = _replace_token_in_yaml_text(text, token)
    atomic_write_text(p, updated, mode=_CONFIG_SECRET_MODE)
    return token


def _enforce_secret_mode(p: Path) -> None:
    """Tighten an existing file to ``0600`` if it's currently broader.

    Idempotent and silent — we never widen permissions.
    """
    import os
    import stat as stat_mod

    try:
        current = stat_mod.S_IMODE(p.stat().st_mode)
    except OSError:
        return
    if current & ~_CONFIG_SECRET_MODE:
        try:
            os.chmod(p, _CONFIG_SECRET_MODE)
        except OSError:
            pass


class ManagerSection(BaseModel):
    # Legacy compatibility field for Wings/Pterodactyl nodes. Non-Wings hosts
    # are addressed by manager_hosts.id on the Manager side and should omit it.
    node_id: int | None = None


class TLSSection(BaseModel):
    """Optional TLS for the agent's own HTTP listener.

    When both files are provided, uvicorn will serve HTTPS on `bind`.
    The cert/key are read once at startup; renewing them requires a systemd
    restart (typically driven by a cert_install_target with reload_cmd=
    `systemctl restart erocraft-agent`).
    """

    cert_path: str
    key_path: str

    @field_validator("cert_path", "key_path")
    @classmethod
    def _required(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("cert_path/key_path must not be empty")
        return v


class AgentSection(BaseModel):
    role: AgentRole = "wings_node"
    bind: str = "0.0.0.0:48765"
    token: str
    allow_ips: list[str] = Field(default_factory=list)
    tls: TLSSection | None = None

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
    proxy: str | None = None


class CertInstallTarget(BaseModel):
    name: str
    cert_path: str
    key_path: str
    reload_cmd: str | None = None

    @field_validator("name")
    @classmethod
    def _required_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v


class LoggingSection(BaseModel):
    level: str = "INFO"


class AgentConfig(BaseModel):
    model_config = {"extra": "forbid"}

    manager: ManagerSection = Field(default_factory=ManagerSection)
    agent: AgentSection
    wings: WingsSection = Field(default_factory=WingsSection)
    collect: CollectSection = Field(default_factory=CollectSection)
    probes: list[ProbeConfig] = Field(default_factory=list)
    cert_install_targets: list[CertInstallTarget] = Field(default_factory=list)
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
