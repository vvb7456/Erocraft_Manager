"""Read /etc/pterodactyl/config.yml and produce sanitized summary + extract daemon_token."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..schemas import WingsConfigSummary


class WingsConfigError(Exception):
    pass


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise WingsConfigError(f"wings config not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise WingsConfigError(f"failed to parse wings config: {e}") from e
    if not isinstance(data, dict):
        raise WingsConfigError("wings config root is not a mapping")
    return data


def read_summary(path: str | Path) -> WingsConfigSummary:
    data = _load_yaml(Path(path))
    api = data.get("api") or {}
    ssl = api.get("ssl") or {}
    sftp = data.get("sftp") or {}
    system = data.get("system") or {}
    docker = data.get("docker") or {}
    return WingsConfigSummary(
        api_host=api.get("host"),
        api_port=api.get("port"),
        api_ssl_enabled=bool(ssl.get("enabled")) if "enabled" in ssl else None,
        api_upload_limit_mb=api.get("upload_limit"),
        sftp_bind_address=sftp.get("address") or sftp.get("bind_address"),
        sftp_bind_port=sftp.get("port") or sftp.get("bind_port"),
        system_data=system.get("data"),
        docker_socket=docker.get("socket"),
        debug=data.get("debug"),
    )


def read_daemon_token(path: str | Path) -> str | None:
    """Wings stores its own bearer token in `token` (plaintext, not encrypted)."""
    data = _load_yaml(Path(path))
    return data.get("token")


def read_local_wings_url(path: str | Path) -> str:
    """Build the loopback URL agent uses to query its local wings."""
    data = _load_yaml(Path(path))
    api = data.get("api") or {}
    port = api.get("port", 8080)
    ssl = api.get("ssl") or {}
    scheme = "https" if ssl.get("enabled") else "http"
    return f"{scheme}://127.0.0.1:{port}"
