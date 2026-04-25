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
    enable_api_docs: bool
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
    panel_app_key: str
    cert_acme_sh_home: str
    cert_acme_sh_bin: str

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


def _required_secret(name: str, *, min_length: int = 32) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise RuntimeError(f"{name} must be set")
    cleaned = value.strip()
    if len(cleaned) < min_length:
        raise RuntimeError(
            f"{name} must be at least {min_length} characters long"
        )
    return cleaned


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise RuntimeError(f"{name} must be set")
    return value.strip()


def _build_settings() -> Settings:
    load_dotenv()
    secret_key = _required_secret("SECRET_KEY")
    settings_encryption_key = os.getenv("SETTINGS_ENCRYPTION_KEY", secret_key).strip() or secret_key
    return Settings(
        app_name=os.getenv("APP_NAME", "Erocraft Manager"),
        app_version=os.getenv("APP_VERSION", "2.0.0"),
        secret_key=secret_key,
        settings_encryption_key=settings_encryption_key,
        default_timezone=os.getenv("TIMEZONE", "Asia/Shanghai"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        enable_api_docs=_as_bool(os.getenv("ENABLE_API_DOCS"), False),
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
        panel_app_key=_env_first("PANEL_APP_KEY", "APP_KEY"),
        cert_acme_sh_home=_required_env("CERT_ACME_SH_HOME"),
        cert_acme_sh_bin=_required_env("CERT_ACME_SH_BIN"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _build_settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
