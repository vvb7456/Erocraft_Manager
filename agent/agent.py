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
from .config import load_config
from .http_app import create_app


def _self_check(cfg, config_path: str) -> None:
    log = logging.getLogger("agent.startup")
    # 1. wings config readable + parseable + has token
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
        "agent v2 starting: node_id=%d bind=%s wings_config=%s probes=%d",
        cfg.manager.node_id,
        cfg.agent.bind,
        cfg.wings.config_path,
        len(cfg.probes),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Erocraft Agent V2")
    parser.add_argument("config", help="path to agent.yaml")
    args = parser.parse_args()

    config_path = str(Path(args.config).resolve())
    cfg = load_config(config_path)

    logging.basicConfig(
        level=cfg.logging.level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    _self_check(cfg, config_path)

    app = create_app(cfg, config_path)
    uvicorn.run(
        app,
        host=cfg.agent.host,
        port=cfg.agent.port,
        log_level=cfg.logging.level.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
