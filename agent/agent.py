#!/usr/bin/env python3
"""Erocraft Agent V2 — node-side ops/monitoring proxy.

Usage:
    python -m agent.agent /path/to/agent.yaml
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import uvicorn

from .collectors import wings_config as wings_config_collector
from .config import bootstrap_agent_token, load_config
from .http_app import create_app


def _self_check(cfg, config_path: str) -> None:
    log = logging.getLogger("agent.startup")
    if cfg.agent.is_wings:
        try:
            wings_config_collector.read_summary(cfg.wings.config_path)
            if not wings_config_collector.read_daemon_token(cfg.wings.config_path):
                log.warning("wings config has no token field; container aggregates will be empty")
        except wings_config_collector.WingsConfigError as e:
            log.error("wings config check failed: %s", e)
            sys.exit(2)
    # Note: port-in-use pre-check removed (used to call psutil.net_connections,
    # which requires either CAP_NET_ADMIN or full /proc enumeration and fails on
    # restricted hosts). uvicorn.run() raises on bind failure, which is good
    # enough as a check.
    log.info(
        "agent v2 starting: role=%s node_id=%s bind=%s wings_config=%s probes=%d",
        cfg.agent.role,
        cfg.manager.node_id if cfg.agent.is_wings else None,
        cfg.agent.bind,
        cfg.wings.config_path if cfg.agent.is_wings else None,
        len(cfg.probes),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Erocraft Agent V2")
    parser.add_argument("config", nargs="?", help="path to agent.yaml (positional)")
    parser.add_argument("--config", dest="config_flag", help="path to agent.yaml (flag)")
    args = parser.parse_args()
    # Support both positional `config` and flag `--config` for compatibility
    if args.config_flag:
        args.config = args.config_flag
    if not args.config:
        parser.error("missing config path")

    config_path = str(Path(args.config).resolve())
    generated_token = bootstrap_agent_token(config_path)
    cfg = load_config(config_path)

    logging.basicConfig(
        level=cfg.logging.level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if generated_token:
        logging.getLogger("agent.startup").warning(
            "AGENT_BOOTSTRAP_TOKEN=%s (written to %s)",
            generated_token,
            config_path,
        )

    _self_check(cfg, config_path)

    app = create_app(cfg, config_path)
    uvicorn.run(
        app,
        host=cfg.agent.host,
        port=cfg.agent.port,
        loop="asyncio",
        log_level=cfg.logging.level.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
