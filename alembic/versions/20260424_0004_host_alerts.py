"""host alert tables + drop deprecated alert/monitor settings.

Revision ID: 20260424_0004
Revises: 20260423_0003
Create Date: 2026-04-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260424_0004"
down_revision = "20260423_0003"
branch_labels = None
depends_on = None


DEPRECATED_SETTING_KEYS: tuple[str, ...] = (
    "MONITOR_ENABLED",
    "MONITOR_NODE_IDS",
    "ALERT_CPU_THRESHOLD",
    "ALERT_CPU_SUSTAIN_MIN",
    "ALERT_MEM_THRESHOLD",
    "ALERT_MEM_SUSTAIN_MIN",
    "ALERT_SWAP_THRESHOLD",
    "ALERT_DISK_WARNING",
    "ALERT_DISK_CRITICAL",
    "ALERT_LOAD_FACTOR",
    "ALERT_LOAD_SUSTAIN_MIN",
    "ALERT_COOLDOWN_MIN",
    "ALERT_EMAIL_ENABLED",
    "ALERT_EMAIL_ADMIN_IDS",
    "ALERT_NOTIFY_RESOLVE",
    "ALERT_MIN_SEVERITY",
    "ALERT_TYPE_NODE_OFFLINE",
    "ALERT_TYPE_AGENT_ONLY_DOWN",
    "ALERT_TYPE_WINGS_ONLY_DOWN",
    "ALERT_TYPE_CPU_HIGH",
    "ALERT_TYPE_MEM_HIGH",
    "ALERT_TYPE_SWAP_HIGH",
    "ALERT_TYPE_DISK_HIGH",
    "ALERT_TYPE_DISK_CRITICAL",
    "ALERT_TYPE_LOAD_HIGH",
    "ALERT_TYPE_NETWORK_DOWN",
    "ALERT_TYPE_CLASH_DOWN",
)


def upgrade() -> None:
    op.create_table(
        "manager_host_alert_settings",
        sa.Column(
            "host_id", sa.Integer(), nullable=False, primary_key=True,
        ),
        sa.Column("email_enabled", sa.Boolean(), nullable=True),
        sa.Column("email_recipients", sa.JSON(), nullable=True),
        sa.Column("min_severity", sa.String(length=20), nullable=True),
        sa.Column("notify_resolve", sa.Boolean(), nullable=True),
        sa.Column("cooldown_min", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["host_id"], ["manager_hosts.id"], ondelete="CASCADE",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )

    op.create_table(
        "manager_host_alert_rules",
        sa.Column(
            "id", sa.Integer(), nullable=False,
            primary_key=True, autoincrement=True,
        ),
        sa.Column("host_id", sa.Integer(), nullable=False),
        sa.Column("alert_type", sa.String(length=50), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("warning_threshold", sa.Float(), nullable=True),
        sa.Column("critical_threshold", sa.Float(), nullable=True),
        sa.Column("sustain_min", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["host_id"], ["manager_hosts.id"], ondelete="CASCADE",
        ),
        sa.UniqueConstraint("host_id", "alert_type", name="uk_host_type"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "idx_host_alert_host", "manager_host_alert_rules", ["host_id"],
    )

    # Drop deprecated runtime settings rows (if present).
    bind = op.get_bind()
    if DEPRECATED_SETTING_KEYS:
        placeholders = ",".join([f":k{i}" for i in range(len(DEPRECATED_SETTING_KEYS))])
        params = {f"k{i}": k for i, k in enumerate(DEPRECATED_SETTING_KEYS)}
        bind.execute(
            sa.text(
                f"DELETE FROM manager_system_settings WHERE `key` IN ({placeholders})"
            ),
            params,
        )


def downgrade() -> None:
    op.drop_index("idx_host_alert_host", table_name="manager_host_alert_rules")
    op.drop_table("manager_host_alert_rules")
    op.drop_table("manager_host_alert_settings")
    # No restore of deleted setting rows — Alembic will repopulate defaults
    # via runtime_settings spec on next startup if needed.
