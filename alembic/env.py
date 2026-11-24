from __future__ import annotations

import inspect
from logging.config import fileConfig
from typing import Any

from alembic import context
from alembic.runtime.environment import EnvironmentContext
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.db import models  # noqa: F401
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    configured_url = config.get_main_option("sqlalchemy.url")
    if configured_url and configured_url != "driver://user:pass@localhost/dbname":
        return configured_url
    return get_settings().sync_database_url


def _common_configure_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "target_metadata": target_metadata,
        "compare_type": True,
    }
    # 开发库历史遗留 server_transfers JSON 列带 '(DC2Type:json)' 注释而生产库无注释；
    # 全库 ORM 均不使用列注释，排除 comments 比对插件以保证双库与空库均零漂移。
    if "autogenerate_plugins" in inspect.signature(EnvironmentContext.configure).parameters:
        kwargs["autogenerate_plugins"] = [
            "alembic.autogenerate.*",
            "~alembic.autogenerate.comments",
        ]
    return kwargs


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_common_configure_kwargs(),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            **_common_configure_kwargs(),
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
