"""System-level default alert configuration.

Per-host alert configuration lives in ``manager_host_alert_settings`` and
``manager_host_alert_rules``. When a host row is missing for a given field
or a rule row is absent for a given alert type, the evaluator falls back to
the values defined here.

These constants are **not** stored in the database — updating them requires
a code change + deploy, which is the intended behaviour for platform-level
hard defaults.
"""

from __future__ import annotations

from typing import Any, Literal


Severity = Literal["warning", "critical"]


# --- Notification-channel defaults ---------------------------------------

DEFAULT_EMAIL_ENABLED: bool = True
DEFAULT_EMAIL_RECIPIENTS: list[int] = []  # admin user IDs; empty = all admins
DEFAULT_MIN_SEVERITY: Severity = "warning"
DEFAULT_NOTIFY_RESOLVE: bool = False
DEFAULT_COOLDOWN_MIN: int = 30

# --- Global monitoring defaults ------------------------------------------

DEFAULT_INTERVAL_SEC: int = 60
DEFAULT_RETENTION_DAYS: int = 30


# --- Per-type rule defaults ----------------------------------------------
#
# Schema per entry:
#   enabled:            bool          — whether this alert fires by default
#   threshold:          float | None  — % or factor (cpu/mem/swap/load)
#   warning_threshold:  float | None  — disk warning %
#   critical_threshold: float | None  — disk critical %
#   sustain_min:        int | None    — minutes the condition must persist

DEFAULT_ALERT_RULES: dict[str, dict[str, Any]] = {
    # Availability (toggle-only)
    "node_offline":     {"enabled": True},
    "agent_only_down":  {"enabled": True},
    "wings_only_down":  {"enabled": True},
    "network_down":     {"enabled": True},
    "clash_down":       {"enabled": True},

    # Resource usage with sustain window
    "cpu_high":  {"enabled": True,  "threshold": 90.0, "sustain_min": 5},
    "mem_high":  {"enabled": True,  "threshold": 90.0, "sustain_min": 5},
    "swap_high": {"enabled": False, "threshold": 50.0, "sustain_min": 5},
    "load_high": {"enabled": False, "threshold": 1.5,  "sustain_min": 5},

    # Disk — dual-threshold
    "disk_high":     {"enabled": True, "warning_threshold": 85.0, "critical_threshold": 95.0},
    "disk_critical": {"enabled": True, "warning_threshold": 85.0, "critical_threshold": 95.0},
}


ALERT_TYPES: tuple[str, ...] = tuple(DEFAULT_ALERT_RULES.keys())


def default_rule(alert_type: str) -> dict[str, Any]:
    """Return a shallow copy of the default rule for ``alert_type``.

    Returns an empty dict (disabled) when the type is unknown, so callers
    can treat unknown types as inert without raising.
    """

    base = DEFAULT_ALERT_RULES.get(alert_type)
    if base is None:
        return {"enabled": False}
    return dict(base)


def merge_rule(alert_type: str, override: dict[str, Any] | None) -> dict[str, Any]:
    """Overlay ``override`` (non-``None`` fields only) on the default rule."""

    merged = default_rule(alert_type)
    if not override:
        return merged
    for key, value in override.items():
        if value is not None:
            merged[key] = value
    return merged
