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

# Manager -> Agent /v1/metrics pull defaults. Per-host overrides live in
# ``manager_host_alert_settings.agent_pull_timeout`` / ``agent_pull_attempts``
# (NULL = inherit these). Cross-border hosts with 500 ms+ RTT should raise
# both; tight 5 s / 3 attempts causes spurious node_offline on jitter.
DEFAULT_AGENT_PULL_TIMEOUT: float = 5.0
DEFAULT_AGENT_PULL_ATTEMPTS: int = 3

# Availability alerts (node_offline / agent_only_down) require this many
# consecutive failed cycles before firing, to absorb transient pull
# timeouts. The window is evaluated in ``_check_offline_sustained`` and
# reuses ``HostAlertRule.sustain_min`` for per-host override. The default
# below is intentionally small (2 minutes = ~2 failed cycles at 60 s) so a
# real outage is still surfaced promptly.
DEFAULT_OFFLINE_SUSTAIN_MIN: int = 2


# --- Per-type rule defaults ----------------------------------------------
#
# Schema per entry:
#   enabled:            bool          — whether this alert fires by default
#   threshold:          float | None  — % or factor (cpu/mem/swap/load)
#   warning_threshold:  float | None  — disk warning %
#   critical_threshold: float | None  — disk critical %
#   sustain_min:        int | None    — minutes the condition must persist

DEFAULT_ALERT_RULES: dict[str, dict[str, Any]] = {
    # Availability. node_offline / agent_only_down carry a sustain_min so
    # a single dropped pull (common on cross-border links) does not fire a
    # critical alert that self-resolves one cycle later.
    "node_offline":     {"enabled": True, "sustain_min": DEFAULT_OFFLINE_SUSTAIN_MIN},
    "agent_only_down":  {"enabled": True, "sustain_min": DEFAULT_OFFLINE_SUSTAIN_MIN},
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

    # Certificate source lifecycle
    "cert_source_expiring": {"enabled": True},
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
