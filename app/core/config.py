"""Application settings for the FastAPI backend."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import quote_plus

from dotenv import load_dotenv


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None and value != "" else default
    except ValueError:
        return default


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return default


@dataclass(slots=True)
class Settings:
    app_name: str
    app_version: str
    secret_key: str
    settings_encryption_key: str
    default_timezone: str
    log_level: str
    session_cookie_name: str
    session_max_age: int
    session_cookie_secure: bool
    session_same_site: str
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str
    database_url: str | None
    async_database_url_override: str | None
    async_database_use_null_pool: bool
    ptero_panel_url: str
    ptero_api_key: str
    panel_app_key: str

    @property
    def sync_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            "mysql+pymysql://"
            f"{quote_plus(self.db_user)}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def async_database_url(self) -> str:
        if self.async_database_url_override:
            return self.async_database_url_override
        if self.database_url:
            if self.database_url.startswith("mysql+pymysql://"):
                return self.database_url.replace("mysql+pymysql://", "mysql+aiomysql://", 1)
            return self.database_url
        return (
            "mysql+aiomysql://"
            f"{quote_plus(self.db_user)}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


def _build_settings() -> Settings:
    load_dotenv()
    secret_key = os.getenv("SECRET_KEY", "a_default_secret_key_for_dev")
    return Settings(
        app_name=os.getenv("APP_NAME", "Erocraft Manager"),
        app_version=os.getenv("APP_VERSION", "2.0.0"),
        secret_key=secret_key,
        settings_encryption_key=os.getenv("SETTINGS_ENCRYPTION_KEY", secret_key),
        default_timezone=os.getenv("TIMEZONE", "Asia/Shanghai"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        session_cookie_name=os.getenv("SESSION_COOKIE_NAME", "erocraft_manager_session"),
        session_max_age=_as_int(os.getenv("SESSION_MAX_AGE"), 60 * 60 * 24 * 14),
        session_cookie_secure=_as_bool(os.getenv("SESSION_COOKIE_SECURE"), False),
        session_same_site=os.getenv("SESSION_SAME_SITE", "lax"),
        db_host=os.getenv("DB_HOST", "127.0.0.1"),
        db_port=_as_int(os.getenv("DB_PORT"), 3306),
        db_user=os.getenv("DB_USER", ""),
        db_password=os.getenv("DB_PASSWORD", ""),
        db_name=os.getenv("DB_NAME", "panel"),
        database_url=os.getenv("DATABASE_URL"),
        async_database_url_override=os.getenv("ASYNC_DATABASE_URL"),
        async_database_use_null_pool=_as_bool(os.getenv("ASYNC_DATABASE_USE_NULL_POOL"), False),
        ptero_panel_url=os.getenv("PTERO_PANEL_URL", "").rstrip("/"),
        ptero_api_key=os.getenv("PTERO_API_KEY", ""),
        panel_app_key=_env_first("PANEL_APP_KEY", "APP_KEY"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _build_settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
