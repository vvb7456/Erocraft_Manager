"""Definitions for DB-backed runtime settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.core.config import get_settings

MASKED_SECRET_VALUE = "********"


def _env_str(name: str, default: str = "") -> str:
    get_settings()
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    get_settings()
    value = os.getenv(name)
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    get_settings()
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _normalize_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_timezone(value: Any) -> str:
    timezone_name = _normalize_str(value) or get_settings().default_timezone
    try:
        ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError(f"无效的时区: {timezone_name}") from exc
    return timezone_name


def _int_clamper(low: int, high: int, default: int) -> Callable[[Any], int]:
    def normalize(value: Any) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(low, min(high, parsed))

    return normalize


def _env_float(name: str, default: float) -> float:
    get_settings()
    value = os.getenv(name)
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


def _float_clamper(low: float, high: float, default: float) -> Callable[[Any], float]:
    def normalize(value: Any) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        return max(low, min(high, parsed))

    return normalize


def _enum_normalizer(allowed: tuple[str, ...], default: str) -> Callable[[Any], str]:
    def normalize(value: Any) -> str:
        s = _normalize_str(value).lower()
        return s if s in allowed else default

    return normalize


@dataclass(frozen=True, slots=True)
class SettingSpec:
    key: str
    category: str
    default_factory: Callable[[], Any]
    normalize: Callable[[Any], Any]
    sensitive: bool = False

    def default_value(self) -> Any:
        return self.default_factory()


# ---------------------------------------------------------------------------
# Spec registry
# ---------------------------------------------------------------------------
# Every ``*_SPECS`` dict in this module must be wrapped by :func:`_register`
# so that :data:`SENSITIVE_KEYS` (and any future module-wide query) is derived
# automatically. Previously ``SENSITIVE_KEYS`` hard-listed
# ``(SETTINGS_SPECS, AUTOMATION_SPECS, MONITORING_SPECS)`` and forgetting to
# add a new dict silently dropped its sensitive keys — see Phase-1 CR §4.6.
# ---------------------------------------------------------------------------

_ALL_SPEC_DICTS: list[dict[str, "SettingSpec"]] = []


def _register(specs: dict[str, "SettingSpec"]) -> dict[str, "SettingSpec"]:
    _ALL_SPEC_DICTS.append(specs)
    return specs


SETTINGS_SPECS: dict[str, SettingSpec] = _register({
    "SMTP_HOST": SettingSpec("SMTP_HOST", "smtp", lambda: _env_str("SMTP_HOST", ""), _normalize_str),
    "SMTP_PORT": SettingSpec("SMTP_PORT", "smtp", lambda: _env_int("SMTP_PORT", 587), _int_clamper(1, 65535, 587)),
    "SMTP_USE_SSL": SettingSpec("SMTP_USE_SSL", "smtp", lambda: _env_bool("SMTP_USE_SSL", True), _normalize_bool),
    "SMTP_PASSWORD": SettingSpec("SMTP_PASSWORD", "smtp", lambda: _env_str("SMTP_PASSWORD", ""), _normalize_str, sensitive=True),
    "SENDER_EMAIL": SettingSpec("SENDER_EMAIL", "smtp", lambda: _env_str("SENDER_EMAIL", ""), _normalize_str),
    "EMAIL_SEND_DELAY": SettingSpec(
        "EMAIL_SEND_DELAY",
        "smtp",
        lambda: _env_int("EMAIL_SEND_DELAY", 2),
        _int_clamper(0, 60, 2),
    ),
    "UI_SYSTEM_NAME": SettingSpec(
        "UI_SYSTEM_NAME",
        "branding",
        lambda: _env_str("UI_SYSTEM_NAME", ""),
        _normalize_str,
    ),
    "SITE_URL": SettingSpec(
        "SITE_URL",
        "branding",
        lambda: _env_str("SITE_URL", ""),
        _normalize_str,
    ),
    "UI_BANNER_URL": SettingSpec("UI_BANNER_URL", "branding", lambda: _env_str("UI_BANNER_URL", ""), _normalize_str),
    "UI_ICP_RECORD": SettingSpec("UI_ICP_RECORD", "branding", lambda: _env_str("UI_ICP_RECORD", ""), _normalize_str),
    "BRAND_NAME": SettingSpec(
        "BRAND_NAME",
        "branding",
        lambda: _env_str("BRAND_NAME", get_settings().app_name),
        _normalize_str,
    ),
    "ALLOW_PUBLIC_REGISTRATION": SettingSpec(
        "ALLOW_PUBLIC_REGISTRATION",
        "account",
        lambda: _env_bool("ALLOW_PUBLIC_REGISTRATION", True),
        _normalize_bool,
    ),
    "DEFAULT_NEST_ID": SettingSpec(
        "DEFAULT_NEST_ID",
        "server_defaults",
        lambda: _env_int("DEFAULT_NEST_ID", 1),
        _int_clamper(1, 999999, 1),
    ),
    "DEFAULT_EGG_ID": SettingSpec(
        "DEFAULT_EGG_ID",
        "server_defaults",
        lambda: _env_int("DEFAULT_EGG_ID", 1),
        _int_clamper(1, 999999, 1),
    ),
    "DEFAULT_NODE_ID": SettingSpec(
        "DEFAULT_NODE_ID",
        "server_defaults",
        lambda: _env_int("DEFAULT_NODE_ID", 1),
        _int_clamper(1, 999999, 1),
    ),
    "DOCKER_IMAGE": SettingSpec(
        "DOCKER_IMAGE",
        "server_defaults",
        lambda: _env_str("DOCKER_IMAGE", "ghcr.io/pterodactyl/yolks:java_17"),
        _normalize_str,
    ),
    "DEFAULT_CPU": SettingSpec(
        "DEFAULT_CPU",
        "server_defaults",
        lambda: _env_int("DEFAULT_CPU", 100),
        _int_clamper(0, 1000000, 100),
    ),
    "DEFAULT_MEMORY": SettingSpec(
        "DEFAULT_MEMORY",
        "server_defaults",
        lambda: _env_int("DEFAULT_MEMORY", 1024),
        _int_clamper(0, 1000000, 1024),
    ),
    "DEFAULT_DISK": SettingSpec(
        "DEFAULT_DISK",
        "server_defaults",
        lambda: _env_int("DEFAULT_DISK", 5120),
        _int_clamper(0, 1000000, 5120),
    ),
    "DEFAULT_DATABASES": SettingSpec(
        "DEFAULT_DATABASES",
        "server_defaults",
        lambda: _env_int("DEFAULT_DATABASES", 0),
        _int_clamper(0, 1000, 0),
    ),
    "DEFAULT_BACKUPS": SettingSpec(
        "DEFAULT_BACKUPS",
        "server_defaults",
        lambda: _env_int("DEFAULT_BACKUPS", 0),
        _int_clamper(0, 1000, 0),
    ),
    "DEFAULT_ALLOCATIONS": SettingSpec(
        "DEFAULT_ALLOCATIONS",
        "server_defaults",
        lambda: _env_int("DEFAULT_ALLOCATIONS", 1),
        _int_clamper(0, 1000, 1),
    ),
    "SERVER_NAME_PREFIX": SettingSpec(
        "SERVER_NAME_PREFIX",
        "server_defaults",
        lambda: _env_str("SERVER_NAME_PREFIX", ""),
        _normalize_str,
    ),
})

AUTOMATION_SPECS: dict[str, SettingSpec] = _register({
    "AUTOMATION_RUN_HOUR": SettingSpec(
        "AUTOMATION_RUN_HOUR",
        "automation",
        lambda: _env_int("AUTOMATION_RUN_HOUR", 2),
        _int_clamper(0, 23, 2),
    ),
    "AUTOMATION_RUN_MINUTE": SettingSpec(
        "AUTOMATION_RUN_MINUTE",
        "automation",
        lambda: _env_int("AUTOMATION_RUN_MINUTE", 0),
        _int_clamper(0, 59, 0),
    ),
    "AUTOMATION_SUSPEND_ENABLED": SettingSpec(
        "AUTOMATION_SUSPEND_ENABLED",
        "automation",
        lambda: _env_bool("AUTOMATION_SUSPEND_ENABLED", False),
        _normalize_bool,
    ),
    "AUTOMATION_DELETE_ENABLED": SettingSpec(
        "AUTOMATION_DELETE_ENABLED",
        "automation",
        lambda: _env_bool("AUTOMATION_DELETE_ENABLED", False),
        _normalize_bool,
    ),
    "AUTOMATION_DELETE_DAYS": SettingSpec(
        "AUTOMATION_DELETE_DAYS",
        "automation",
        lambda: _env_int("AUTOMATION_DELETE_DAYS", 14),
        _int_clamper(0, 365, 14),
    ),
    "AUTOMATION_EMAIL_ENABLED": SettingSpec(
        "AUTOMATION_EMAIL_ENABLED",
        "automation",
        lambda: _env_bool("AUTOMATION_EMAIL_ENABLED", False),
        _normalize_bool,
    ),
    "AUTOMATION_EMAIL_RUN_HOUR": SettingSpec(
        "AUTOMATION_EMAIL_RUN_HOUR",
        "automation",
        lambda: _env_int("AUTOMATION_EMAIL_RUN_HOUR", 10),
        _int_clamper(0, 23, 10),
    ),
    "AUTOMATION_EMAIL_RUN_MINUTE": SettingSpec(
        "AUTOMATION_EMAIL_RUN_MINUTE",
        "automation",
        lambda: _env_int("AUTOMATION_EMAIL_RUN_MINUTE", 0),
        _int_clamper(0, 59, 0),
    ),
    "TIMEZONE": SettingSpec(
        "TIMEZONE",
        "automation",
        lambda: _env_str("TIMEZONE", get_settings().default_timezone),
        _normalize_timezone,
    ),
})


def defaults_for(specs: dict[str, SettingSpec]) -> dict[str, Any]:
    return {key: spec.default_value() for key, spec in specs.items()}


def _normalize_id_list(value: Any) -> str:
    """Normalize a comma-separated list of integer IDs."""
    raw = _normalize_str(value)
    if not raw:
        return ""
    parts = [x.strip() for x in raw.split(",") if x.strip().isdigit()]
    return ",".join(parts)


MONITORING_SPECS: dict[str, SettingSpec] = _register({
    "MONITOR_ENABLED": SettingSpec(
        "MONITOR_ENABLED", "monitoring",
        lambda: _env_bool("MONITOR_ENABLED", True), _normalize_bool,
    ),
    "MONITOR_NODE_IDS": SettingSpec(
        "MONITOR_NODE_IDS", "monitoring",
        lambda: _env_str("MONITOR_NODE_IDS", ""), _normalize_id_list,
    ),
    "MONITOR_RETENTION_DAYS": SettingSpec(
        "MONITOR_RETENTION_DAYS", "monitoring",
        lambda: _env_int("MONITOR_RETENTION_DAYS", 30), _int_clamper(1, 365, 30),
    ),
    "MONITOR_INTERVAL_SEC": SettingSpec(
        "MONITOR_INTERVAL_SEC", "monitoring",
        lambda: _env_int("MONITOR_INTERVAL_SEC", 60), _int_clamper(30, 3600, 60),
    ),
    "ALERT_CPU_THRESHOLD": SettingSpec(
        "ALERT_CPU_THRESHOLD", "monitoring",
        lambda: _env_int("ALERT_CPU_THRESHOLD", 90), _int_clamper(50, 100, 90),
    ),
    "ALERT_CPU_SUSTAIN_MIN": SettingSpec(
        "ALERT_CPU_SUSTAIN_MIN", "monitoring",
        lambda: _env_int("ALERT_CPU_SUSTAIN_MIN", 5), _int_clamper(1, 60, 5),
    ),
    "ALERT_MEM_THRESHOLD": SettingSpec(
        "ALERT_MEM_THRESHOLD", "monitoring",
        lambda: _env_int("ALERT_MEM_THRESHOLD", 90), _int_clamper(50, 100, 90),
    ),
    "ALERT_MEM_SUSTAIN_MIN": SettingSpec(
        "ALERT_MEM_SUSTAIN_MIN", "monitoring",
        lambda: _env_int("ALERT_MEM_SUSTAIN_MIN", 5), _int_clamper(1, 60, 5),
    ),
    "ALERT_SWAP_THRESHOLD": SettingSpec(
        "ALERT_SWAP_THRESHOLD", "monitoring",
        lambda: _env_int("ALERT_SWAP_THRESHOLD", 50), _int_clamper(10, 100, 50),
    ),
    "ALERT_DISK_WARNING": SettingSpec(
        "ALERT_DISK_WARNING", "monitoring",
        lambda: _env_int("ALERT_DISK_WARNING", 85), _int_clamper(50, 100, 85),
    ),
    "ALERT_DISK_CRITICAL": SettingSpec(
        "ALERT_DISK_CRITICAL", "monitoring",
        lambda: _env_int("ALERT_DISK_CRITICAL", 95), _int_clamper(50, 100, 95),
    ),
    "ALERT_LOAD_FACTOR": SettingSpec(
        "ALERT_LOAD_FACTOR", "monitoring",
        lambda: _env_float("ALERT_LOAD_FACTOR", 1.5), _float_clamper(0.5, 5.0, 1.5),
    ),
    "ALERT_LOAD_SUSTAIN_MIN": SettingSpec(
        "ALERT_LOAD_SUSTAIN_MIN", "monitoring",
        lambda: _env_int("ALERT_LOAD_SUSTAIN_MIN", 5), _int_clamper(1, 60, 5),
    ),
    "ALERT_COOLDOWN_MIN": SettingSpec(
        "ALERT_COOLDOWN_MIN", "monitoring",
        lambda: _env_int("ALERT_COOLDOWN_MIN", 30), _int_clamper(1, 1440, 30),
    ),
    # --- Notification channel ---
    "ALERT_EMAIL_ENABLED": SettingSpec(
        "ALERT_EMAIL_ENABLED", "monitoring",
        lambda: _env_bool("ALERT_EMAIL_ENABLED", False), _normalize_bool,
    ),
    "ALERT_EMAIL_ADMIN_IDS": SettingSpec(
        "ALERT_EMAIL_ADMIN_IDS", "monitoring",
        lambda: _env_str("ALERT_EMAIL_ADMIN_IDS", ""), _normalize_id_list,
    ),
    "ALERT_NOTIFY_RESOLVE": SettingSpec(
        "ALERT_NOTIFY_RESOLVE", "monitoring",
        lambda: _env_bool("ALERT_NOTIFY_RESOLVE", False), _normalize_bool,
    ),
    "ALERT_MIN_SEVERITY": SettingSpec(
        "ALERT_MIN_SEVERITY", "monitoring",
        lambda: _env_str("ALERT_MIN_SEVERITY", "warning"),
        _enum_normalizer(("warning", "critical"), "warning"),
    ),
    # --- Per-type toggles ---
    "ALERT_TYPE_NODE_OFFLINE": SettingSpec(
        "ALERT_TYPE_NODE_OFFLINE", "monitoring",
        lambda: _env_bool("ALERT_TYPE_NODE_OFFLINE", True), _normalize_bool,
    ),
    "ALERT_TYPE_AGENT_ONLY_DOWN": SettingSpec(
        "ALERT_TYPE_AGENT_ONLY_DOWN", "monitoring",
        lambda: _env_bool("ALERT_TYPE_AGENT_ONLY_DOWN", True), _normalize_bool,
    ),
    "ALERT_TYPE_WINGS_ONLY_DOWN": SettingSpec(
        "ALERT_TYPE_WINGS_ONLY_DOWN", "monitoring",
        lambda: _env_bool("ALERT_TYPE_WINGS_ONLY_DOWN", True), _normalize_bool,
    ),
    "ALERT_TYPE_CPU_HIGH": SettingSpec(
        "ALERT_TYPE_CPU_HIGH", "monitoring",
        lambda: _env_bool("ALERT_TYPE_CPU_HIGH", True), _normalize_bool,
    ),
    "ALERT_TYPE_MEM_HIGH": SettingSpec(
        "ALERT_TYPE_MEM_HIGH", "monitoring",
        lambda: _env_bool("ALERT_TYPE_MEM_HIGH", True), _normalize_bool,
    ),
    "ALERT_TYPE_SWAP_HIGH": SettingSpec(
        "ALERT_TYPE_SWAP_HIGH", "monitoring",
        lambda: _env_bool("ALERT_TYPE_SWAP_HIGH", False), _normalize_bool,
    ),
    "ALERT_TYPE_DISK_HIGH": SettingSpec(
        "ALERT_TYPE_DISK_HIGH", "monitoring",
        lambda: _env_bool("ALERT_TYPE_DISK_HIGH", True), _normalize_bool,
    ),
    "ALERT_TYPE_DISK_CRITICAL": SettingSpec(
        "ALERT_TYPE_DISK_CRITICAL", "monitoring",
        lambda: _env_bool("ALERT_TYPE_DISK_CRITICAL", True), _normalize_bool,
    ),
    "ALERT_TYPE_LOAD_HIGH": SettingSpec(
        "ALERT_TYPE_LOAD_HIGH", "monitoring",
        lambda: _env_bool("ALERT_TYPE_LOAD_HIGH", False), _normalize_bool,
    ),
    "ALERT_TYPE_NETWORK_DOWN": SettingSpec(
        "ALERT_TYPE_NETWORK_DOWN", "monitoring",
        lambda: _env_bool("ALERT_TYPE_NETWORK_DOWN", True), _normalize_bool,
    ),
    "ALERT_TYPE_CLASH_DOWN": SettingSpec(
        "ALERT_TYPE_CLASH_DOWN", "monitoring",
        lambda: _env_bool("ALERT_TYPE_CLASH_DOWN", True), _normalize_bool,
    ),
})


# ---------------------------------------------------------------------------
# Sensitive-key registry
#
# Built from the explicit `sensitive=True` flag on each SettingSpec.
# Used by both the storage layer (for at-rest encryption) and the API layer
# (for response masking).  No substring matching — each sensitive key must
# be opted in explicitly on its spec.
# ---------------------------------------------------------------------------

SENSITIVE_KEYS: frozenset[str] = frozenset(
    spec.key
    for specs in _ALL_SPEC_DICTS
    for spec in specs.values()
    if spec.sensitive
)
