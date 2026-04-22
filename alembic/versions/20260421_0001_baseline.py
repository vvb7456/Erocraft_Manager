"""Squashed baseline for all manager_* tables.

This single migration replaces the previous chain of seven incremental
migrations + one merge node that accumulated during early Phase 1
development (see git history before commit replacing them).

Replaces:
    20260417_0001_manager_tables_baseline
    20260419_0002_account_tables
    20260419_0003_email_template_table
    20260419_0004_structured_activity_logs
    20260420_0005_node_metrics_swap_uptime
    20260928_0005_monitoring_tables   (file-name was a date typo)
    ceced0258468_merge_heads
    20260421_0006_node_meta_agent

The schema produced here is byte-for-byte equivalent to running the old
chain to head, with the following intentional cleanups:
  * Single, deterministic revision identifier
  * No collisions on the short numeric suffix (the old chain had two
    ``..._0005_*`` files)
  * No machine-generated merge node
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260421_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- core meta -------------------------------------------------------
    op.create_table(
        "manager_server_meta",
        sa.Column("server_id", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("server_id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )

    # --- activity logs ---------------------------------------------------
    op.create_table(
        "manager_activity_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "timestamp",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("detail_key", sa.String(length=120), nullable=True),
        sa.Column("detail_params", sa.Text(), nullable=True),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("idx_timestamp", "manager_activity_logs", ["timestamp"])
    op.create_index("idx_actor", "manager_activity_logs", ["actor"])
    op.create_index("idx_action", "manager_activity_logs", ["action"])

    # --- system settings -------------------------------------------------
    op.create_table(
        "manager_system_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "value_type",
            sa.String(length=16),
            nullable=False,
            server_default="string",
        ),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("key"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("idx_category", "manager_system_settings", ["category"])

    # --- account self-service -------------------------------------------
    op.create_table(
        "manager_password_resets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("idx_pw_reset_user_id", "manager_password_resets", ["user_id"])

    op.create_table(
        "manager_email_changes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("new_email", sa.String(length=255), nullable=False),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("idx_email_change_user_id", "manager_email_changes", ["user_id"])

    op.create_table(
        "manager_pending_registrations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=191), nullable=False),
        sa.Column("first_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("last_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("lookup_hash", sa.String(length=64), nullable=False),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("idx_pr_email", "manager_pending_registrations", ["email"])
    op.create_index("idx_pr_username", "manager_pending_registrations", ["username"])
    op.create_index(
        "uq_pr_lookup_hash",
        "manager_pending_registrations",
        ["lookup_hash"],
        unique=True,
    )

    # --- email templates -------------------------------------------------
    op.create_table(
        "manager_email_templates",
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("template_key"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )

    # --- monitoring: node metrics ---------------------------------------
    op.create_table(
        "manager_node_metrics",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("node_id", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False),
        # online status
        sa.Column("agent_online", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("wings_online", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("public_reachable", sa.Boolean(), nullable=True),
        # host metrics (from agent)
        sa.Column("cpu_pct", sa.Float(), nullable=True),
        sa.Column("cpu_cores", sa.SmallInteger(), nullable=True),
        sa.Column("load_1m", sa.Float(), nullable=True),
        sa.Column("load_5m", sa.Float(), nullable=True),
        sa.Column("load_15m", sa.Float(), nullable=True),
        sa.Column("mem_total_mb", sa.Integer(), nullable=True),
        sa.Column("mem_used_mb", sa.Integer(), nullable=True),
        sa.Column("mem_pct", sa.Float(), nullable=True),
        sa.Column("disk_total_mb", sa.Integer(), nullable=True),
        sa.Column("disk_used_mb", sa.Integer(), nullable=True),
        sa.Column("disk_pct", sa.Float(), nullable=True),
        sa.Column("net_rx_bps", sa.BigInteger(), nullable=True),
        sa.Column("net_tx_bps", sa.BigInteger(), nullable=True),
        # wings container aggregates
        sa.Column("wings_version", sa.String(length=20), nullable=True),
        sa.Column("container_total", sa.SmallInteger(), nullable=True),
        sa.Column("container_running", sa.SmallInteger(), nullable=True),
        sa.Column("container_mem_mb", sa.Integer(), nullable=True),
        sa.Column("container_cpu_pct", sa.Float(), nullable=True),
        sa.Column("container_disk_mb", sa.Integer(), nullable=True),
        # extras (originally added in 20260420_0005)
        sa.Column("swap_total_mb", sa.Integer(), nullable=True),
        sa.Column("swap_used_mb", sa.Integer(), nullable=True),
        sa.Column("uptime_sec", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("idx_nm_node_ts", "manager_node_metrics", ["node_id", "ts"])
    op.create_index("idx_nm_ts", "manager_node_metrics", ["ts"])

    # --- monitoring: probe results --------------------------------------
    op.create_table(
        "manager_probe_results",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("probe_name", sa.String(length=50), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("error_msg", sa.String(length=200), nullable=True),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("idx_pr_ts", "manager_probe_results", ["ts"])
    op.create_index("idx_pr_probe_ts", "manager_probe_results", ["probe_name", "ts"])

    # --- monitoring: node alerts ----------------------------------------
    op.create_table(
        "manager_node_alerts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("node_id", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column("alert_type", sa.String(length=30), nullable=False),
        sa.Column(
            "severity",
            sa.String(length=10),
            nullable=False,
            server_default="warning",
        ),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("notified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_notified_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("idx_na_node_active", "manager_node_alerts", ["node_id", "resolved_at"])
    op.create_index("idx_na_created", "manager_node_alerts", ["created_at"])

    # --- per-node agent meta --------------------------------------------
    op.create_table(
        "manager_node_meta",
        sa.Column("node_id", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("agent_endpoint", sa.String(length=200), nullable=True),
        sa.Column("agent_token_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("node_id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("manager_node_meta")
    op.drop_index("idx_na_created", table_name="manager_node_alerts")
    op.drop_index("idx_na_node_active", table_name="manager_node_alerts")
    op.drop_table("manager_node_alerts")
    op.drop_index("idx_pr_probe_ts", table_name="manager_probe_results")
    op.drop_index("idx_pr_ts", table_name="manager_probe_results")
    op.drop_table("manager_probe_results")
    op.drop_index("idx_nm_ts", table_name="manager_node_metrics")
    op.drop_index("idx_nm_node_ts", table_name="manager_node_metrics")
    op.drop_table("manager_node_metrics")
    op.drop_table("manager_email_templates")
    op.drop_index("uq_pr_lookup_hash", table_name="manager_pending_registrations")
    op.drop_index("idx_pr_username", table_name="manager_pending_registrations")
    op.drop_index("idx_pr_email", table_name="manager_pending_registrations")
    op.drop_table("manager_pending_registrations")
    op.drop_index("idx_email_change_user_id", table_name="manager_email_changes")
    op.drop_table("manager_email_changes")
    op.drop_index("idx_pw_reset_user_id", table_name="manager_password_resets")
    op.drop_table("manager_password_resets")
    op.drop_index("idx_category", table_name="manager_system_settings")
    op.drop_table("manager_system_settings")
    op.drop_index("idx_action", table_name="manager_activity_logs")
    op.drop_index("idx_actor", table_name="manager_activity_logs")
    op.drop_index("idx_timestamp", table_name="manager_activity_logs")
    op.drop_table("manager_activity_logs")
    op.drop_table("manager_server_meta")
