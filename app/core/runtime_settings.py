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


# REFERRAL_QUALIFYING_KINDS is stored as a JSON list. Env-var overrides come
# in as CSV strings (env vars can't carry JSON cleanly), so the env reader
# parses those; the normalize path expects a list/tuple from the API.
_QUALIFYING_KIND_VALUES = ("new_purchase", "renew", "upgrade")


def _env_kinds_list(name: str, default: list[str]) -> list[str]:
    get_settings()
    raw = os.getenv(name)
    if raw is None or raw == "":
        return list(default)
    return _normalize_kinds_list([s.strip() for s in raw.split(",")])


def _normalize_kinds_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = [str(s).strip() for s in value]
    else:
        items = [str(value).strip()]
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it and it in _QUALIFYING_KIND_VALUES and it not in seen:
            seen.add(it)
            out.append(it)
    return out


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
    "UI_TUTORIAL_URL": SettingSpec("UI_TUTORIAL_URL", "branding", lambda: _env_str("UI_TUTORIAL_URL", ""), _normalize_str),
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
    "AGREEMENTS_DEFAULT_CHECKED": SettingSpec(
        "AGREEMENTS_DEFAULT_CHECKED",
        "agreements",
        lambda: _env_bool("AGREEMENTS_DEFAULT_CHECKED", False),
        _normalize_bool,
    ),
    # ---- Support contact info (shown in SupportModal, public-readable) ----
    "SUPPORT_EMAIL": SettingSpec(
        "SUPPORT_EMAIL", "branding",
        lambda: _env_str("SUPPORT_EMAIL", ""),
        _normalize_str,
    ),
    "SUPPORT_QQ_GROUP": SettingSpec(
        "SUPPORT_QQ_GROUP", "branding",
        lambda: _env_str("SUPPORT_QQ_GROUP", ""),
        _normalize_str,
    ),
    "SUPPORT_QQ": SettingSpec(
        "SUPPORT_QQ", "branding",
        lambda: _env_str("SUPPORT_QQ", ""),
        _normalize_str,
    ),
    "SUPPORT_WECHAT": SettingSpec(
        "SUPPORT_WECHAT", "branding",
        lambda: _env_str("SUPPORT_WECHAT", ""),
        _normalize_str,
    ),
    "SUPPORT_FOOTER_NOTE": SettingSpec(
        "SUPPORT_FOOTER_NOTE", "branding",
        lambda: _env_str("SUPPORT_FOOTER_NOTE", ""),
        _normalize_str,
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
    "MONITOR_RETENTION_DAYS": SettingSpec(
        "MONITOR_RETENTION_DAYS", "monitoring",
        lambda: _env_int("MONITOR_RETENTION_DAYS", 30), _int_clamper(1, 365, 30),
    ),
    "MONITOR_INTERVAL_SEC": SettingSpec(
        "MONITOR_INTERVAL_SEC", "monitoring",
        lambda: _env_int("MONITOR_INTERVAL_SEC", 60), _int_clamper(30, 3600, 60),
    ),
    "ALERT_DEFAULT_RECIPIENTS": SettingSpec(
        "ALERT_DEFAULT_RECIPIENTS", "monitoring",
        lambda: _env_str("ALERT_DEFAULT_RECIPIENTS", ""), _normalize_id_list,
    ),
})


CERTIFICATE_SPECS: dict[str, SettingSpec] = _register({
    "CERT_WEBHOOK_TOKEN": SettingSpec(
        "CERT_WEBHOOK_TOKEN",
        "certificates",
        lambda: _env_str("CERT_WEBHOOK_TOKEN", ""),
        _normalize_str,
        sensitive=True,
    ),
    "CERT_ALERT_EMAIL_ENABLED": SettingSpec(
        "CERT_ALERT_EMAIL_ENABLED",
        "certificates",
        lambda: _env_bool("CERT_ALERT_EMAIL_ENABLED", True),
        _normalize_bool,
    ),
    "CERT_ALERT_EMAIL_ADMIN_IDS": SettingSpec(
        "CERT_ALERT_EMAIL_ADMIN_IDS",
        "certificates",
        lambda: _env_str("CERT_ALERT_EMAIL_ADMIN_IDS", ""),
        _normalize_id_list,
    ),
})


BILLING_SPECS: dict[str, SettingSpec] = _register({
    # ---- Hupijiao gateway credentials (B-class, UI-editable, sensitive) ----
    "HUPIJIAO_APPID": SettingSpec(
        "HUPIJIAO_APPID", "billing",
        lambda: _env_str("HUPIJIAO_APPID", ""),
        _normalize_str,
        sensitive=True,
    ),
    "HUPIJIAO_APPSECRET": SettingSpec(
        "HUPIJIAO_APPSECRET", "billing",
        lambda: _env_str("HUPIJIAO_APPSECRET", ""),
        _normalize_str,
        sensitive=True,
    ),
    "HUPIJIAO_ENABLED": SettingSpec(
        "HUPIJIAO_ENABLED", "billing",
        lambda: _env_bool("HUPIJIAO_ENABLED", False),
        _normalize_bool,
    ),
    "HUPIJIAO_DISPLAY_NAME": SettingSpec(
        "HUPIJIAO_DISPLAY_NAME", "billing",
        lambda: _env_str("HUPIJIAO_DISPLAY_NAME", "支付宝"),
        _normalize_str,
    ),
    # ---- Hupijiao gateway runtime config (B-class, UI-editable) ----
    # NOTE: notify_url + return_url are auto-derived from SITE_URL by the
    # backend (see app/services/billing/orders.py::_runtime_site_url) and
    # therefore not exposed here. Only fields that genuinely require admin
    # input (REFERER for Hupijiao server-side check, endpoint pool) remain.
    "HUPIJIAO_REFERER": SettingSpec(
        "HUPIJIAO_REFERER", "billing",
        lambda: _env_str("HUPIJIAO_REFERER", "https://app.erocraft.com/"),
        _normalize_str,
    ),
    "HUPIJIAO_GATEWAY_ENDPOINTS": SettingSpec(
        "HUPIJIAO_GATEWAY_ENDPOINTS", "billing",
        lambda: _env_str(
            "HUPIJIAO_GATEWAY_ENDPOINTS",
            "https://api.xunhupay.com,https://api.dpweixin.com",
        ),
        _normalize_str,
    ),
    # ---- Alipay direct gateway (open-platform, RSA2, H5/wap channel) ----
    # Distinct from 虎皮椒: talks straight to open.alipay.com gateway.
    "ALIPAY_DIRECT_ENABLED": SettingSpec(
        "ALIPAY_DIRECT_ENABLED", "billing",
        lambda: _env_bool("ALIPAY_DIRECT_ENABLED", False),
        _normalize_bool,
    ),
    "ALIPAY_DIRECT_APPID": SettingSpec(
        "ALIPAY_DIRECT_APPID", "billing",
        lambda: _env_str("ALIPAY_DIRECT_APPID", ""),
        _normalize_str,
        sensitive=True,
    ),
    "ALIPAY_DIRECT_APP_PRIVATE_KEY": SettingSpec(
        "ALIPAY_DIRECT_APP_PRIVATE_KEY", "billing",
        lambda: _env_str("ALIPAY_DIRECT_APP_PRIVATE_KEY", ""),
        _normalize_str,
        sensitive=True,
    ),
    "ALIPAY_DIRECT_ALIPAY_PUBLIC_KEY": SettingSpec(
        "ALIPAY_DIRECT_ALIPAY_PUBLIC_KEY", "billing",
        lambda: _env_str("ALIPAY_DIRECT_ALIPAY_PUBLIC_KEY", ""),
        _normalize_str,
        sensitive=True,
    ),
    "ALIPAY_DIRECT_GATEWAY": SettingSpec(
        "ALIPAY_DIRECT_GATEWAY", "billing",
        lambda: _env_str(
            "ALIPAY_DIRECT_GATEWAY",
            "https://openapi.alipay.com/gateway.do",
        ),
        _normalize_str,
    ),
    "ALIPAY_DIRECT_SELLER_ID": SettingSpec(
        "ALIPAY_DIRECT_SELLER_ID", "billing",
        lambda: _env_str("ALIPAY_DIRECT_SELLER_ID", ""),
        _normalize_str,
    ),
    "ALIPAY_DIRECT_DISPLAY_NAME": SettingSpec(
        "ALIPAY_DIRECT_DISPLAY_NAME", "billing",
        lambda: _env_str("ALIPAY_DIRECT_DISPLAY_NAME", "支付宝"),
        _normalize_str,
    ),
    # ---- Billing runtime parameters ----
    # 5 min hard cap — payment QR codes typically valid up to 5 min.
    "BILLING_ORDER_PAY_TIMEOUT_MIN": SettingSpec(
        "BILLING_ORDER_PAY_TIMEOUT_MIN", "billing",
        lambda: _env_int("BILLING_ORDER_PAY_TIMEOUT_MIN", 5),
        _int_clamper(3, 5, 5),
    ),
    # refund_retry job runs every 15 min; if a refund stays PENDING beyond
    # this many hours it becomes a manager incident.
    "BILLING_REFUND_STUCK_HOURS": SettingSpec(
        "BILLING_REFUND_STUCK_HOURS", "billing",
        lambda: _env_int("BILLING_REFUND_STUCK_HOURS", 24),
        _int_clamper(1, 168, 24),
    ),
    # ---- Referral / coupon system (docs/REFERRAL_AND_COUPON_DESIGN.md) ----
    # Master switch — when False, the invite link still works (capturing
    # inviter_user_id on register) but no coupons are issued when the
    # invitee places their first qualifying order. Lets us flip the
    # incentive on/off without losing audit history.
    "REFERRAL_REWARD_ENABLED": SettingSpec(
        "REFERRAL_REWARD_ENABLED", "billing",
        lambda: _env_bool("REFERRAL_REWARD_ENABLED", False),
        _normalize_bool,
    ),
    # Template codes (not ids) so the system survives template re-seeds.
    # The referral_rewards service resolves codes → templates at grant
    # time. Defaults match the built-in seed in 20260524_coupons migration.
    "REFERRAL_INVITER_TEMPLATE_CODE": SettingSpec(
        "REFERRAL_INVITER_TEMPLATE_CODE", "billing",
        lambda: _env_str("REFERRAL_INVITER_TEMPLATE_CODE", "REFERRAL_INVITER"),
        _normalize_str,
    ),
    "REFERRAL_INVITEE_TEMPLATE_CODE": SettingSpec(
        "REFERRAL_INVITEE_TEMPLATE_CODE", "billing",
        lambda: _env_str("REFERRAL_INVITEE_TEMPLATE_CODE", "REFERRAL_INVITEE"),
        _normalize_str,
    ),
    # Minimum order subtotal (in fen) the invitee must pay to qualify as
    # the "first qualifying order" that triggers paired coupon issuance.
    # Default 1 fen = "any paid order qualifies". Raise this to filter
    # out throwaway tiny orders if abuse becomes an issue.
    "REFERRAL_QUALIFYING_MIN_FEN": SettingSpec(
        "REFERRAL_QUALIFYING_MIN_FEN", "billing",
        lambda: _env_int("REFERRAL_QUALIFYING_MIN_FEN", 1),
        _int_clamper(1, 1_000_000, 1),
    ),
    # JSON list of order ``kind`` values that trigger paired-coupon
    # issuance. Default mirrors the doc: any first-paid order counts.
    # Set to a narrower list (e.g. ``["new_purchase"]``) to restrict
    # rewards to first-time purchases only. Stored as a JSON list under
    # the hood (settings_store handles ser/de via value_type=json).
    "REFERRAL_QUALIFYING_KINDS": SettingSpec(
        "REFERRAL_QUALIFYING_KINDS", "billing",
        lambda: _env_kinds_list(
            "REFERRAL_QUALIFYING_KINDS", ["new_purchase", "renew", "upgrade"]
        ),
        _normalize_kinds_list,
    ),
})


LLM_SPECS: dict[str, SettingSpec] = _register({
    # ---- LLM free quota (docs/LLM_FREE_QUOTA_DESIGN.md) ----
    # Master switch — when False, all LLM provision/inject/sync hooks are
    # no-ops. Lets admins disable the feature without removing config.
    "LLM_ENABLED": SettingSpec(
        "LLM_ENABLED", "llm",
        lambda: _env_bool("LLM_ENABLED", False),
        _normalize_bool,
    ),
    # NewAPI management API base URL (no trailing /v1). Used by Manager to
    # call admin endpoints (POST /api/user/, POST /api/token/, etc.).
    "NEWAPI_BASE_URL": SettingSpec(
        "NEWAPI_BASE_URL", "llm",
        lambda: _env_str("NEWAPI_BASE_URL", ""),
        _normalize_str,
    ),
    # NewAPI root admin AccessToken (Authorization: Bearer <token>). Sensitive.
    "NEWAPI_ADMIN_TOKEN": SettingSpec(
        "NEWAPI_ADMIN_TOKEN", "llm",
        lambda: _env_str("NEWAPI_ADMIN_TOKEN", ""),
        _normalize_str,
        sensitive=True,
    ),
    # API endpoint URL written into SillyTavern containers (should be
    # reachable from all nodes' ST containers). Usually NEWAPI_BASE_URL + /v1
    # but can differ if NewAPI is behind a different public-facing reverse proxy.
    "LLM_ST_ENDPOINT_URL": SettingSpec(
        "LLM_ST_ENDPOINT_URL", "llm",
        lambda: _env_str("LLM_ST_ENDPOINT_URL", ""),
        _normalize_str,
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
