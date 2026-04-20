"""Database-backed runtime settings store."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decrypt_value, encrypt_value, is_sensitive_setting
from app.db.models.manager import SystemSetting

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _CachedValue:
    value: Any
    expires_at: float


class SettingsStore:
    def __init__(self, cache_ttl_seconds: float = 5.0) -> None:
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, _CachedValue] = {}

    async def get(self, db: AsyncSession, key: str, default: Any = None) -> Any:
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and cached.expires_at > now:
            return cached.value

        try:
            result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
        except SQLAlchemyError:
            logger.warning("Failed to load setting %s; falling back to default", key, exc_info=True)
            return default

        setting = result.scalar_one_or_none()
        if setting is None:
            return default

        value = self._deserialize(setting)
        self._cache[key] = _CachedValue(value=value, expires_at=now + self._cache_ttl_seconds)
        return value

    async def get_many(
        self,
        db: AsyncSession,
        defaults: dict[str, Any],
    ) -> dict[str, Any]:
        now = time.monotonic()
        values: dict[str, Any] = {}
        missing_keys: list[str] = []

        for key, default in defaults.items():
            cached = self._cache.get(key)
            if cached and cached.expires_at > now:
                values[key] = cached.value
            else:
                missing_keys.append(key)

        if not missing_keys:
            return values

        try:
            result = await db.execute(select(SystemSetting).where(SystemSetting.key.in_(missing_keys)))
        except SQLAlchemyError:
            logger.warning("Failed to load settings in bulk; falling back to defaults", exc_info=True)
            for key in missing_keys:
                values[key] = defaults[key]
            return values

        rows = {setting.key: setting for setting in result.scalars().all()}
        for key in missing_keys:
            setting = rows.get(key)
            if setting is None:
                values[key] = defaults[key]
                continue

            value = self._deserialize(setting)
            self._cache[key] = _CachedValue(value=value, expires_at=now + self._cache_ttl_seconds)
            values[key] = value

        return values

    async def set_values(
        self,
        db: AsyncSession,
        values: dict[str, Any],
        *,
        category: str = "runtime",
        commit: bool = True,
    ) -> None:
        if not values:
            return

        result = await db.execute(select(SystemSetting).where(SystemSetting.key.in_(values.keys())))
        existing = {setting.key: setting for setting in result.scalars().all()}

        for key, value in values.items():
            setting = existing.get(key)
            value_type, value_text, value_encrypted = self._serialize(key, value)

            if setting is None:
                setting = SystemSetting(
                    key=key,
                    category=category,
                    value_type=value_type,
                    value_text=value_text,
                    value_encrypted=value_encrypted,
                    version=1,
                )
                db.add(setting)
            else:
                setting.category = category
                setting.value_type = value_type
                setting.value_text = value_text
                setting.value_encrypted = value_encrypted
                setting.version += 1

            self._cache.pop(key, None)

        if commit:
            await db.commit()

    def invalidate(self, *keys: str) -> None:
        for key in keys:
            self._cache.pop(key, None)

    def clear(self) -> None:
        self._cache.clear()

    def _serialize(self, key: str, value: Any) -> tuple[str, str | None, str | None]:
        if isinstance(value, bool):
            serialized = "true" if value else "false"
            value_type = "bool"
        elif isinstance(value, int):
            serialized = str(value)
            value_type = "int"
        elif isinstance(value, (dict, list)):
            serialized = json.dumps(value, ensure_ascii=False)
            value_type = "json"
        else:
            serialized = str(value)
            value_type = "string"

        if is_sensitive_setting(key):
            secret = get_settings().settings_encryption_key
            return value_type, None, encrypt_value(serialized, secret)
        return value_type, serialized, None

    def _deserialize(self, setting: SystemSetting) -> Any:
        raw_value = setting.value_text
        if setting.value_encrypted:
            raw_value = decrypt_value(setting.value_encrypted, get_settings().settings_encryption_key)

        if raw_value is None:
            return None

        if setting.value_type == "bool":
            return raw_value.lower() == "true"
        if setting.value_type == "int":
            return int(raw_value)
        if setting.value_type == "json":
            return json.loads(raw_value)
        return raw_value


@lru_cache(maxsize=1)
def get_settings_store() -> SettingsStore:
    return SettingsStore()
