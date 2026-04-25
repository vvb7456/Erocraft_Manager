"""certificate registry and deployments.

Revision ID: 20260425_0006
Revises: 20260425_0005
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260425_0006"
down_revision = "20260425_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manager_certificates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("domains", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_path", sa.String(length=512), nullable=False),
        sa.Column("source_fingerprint_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_not_before", sa.DateTime(), nullable=True),
        sa.Column("source_not_after", sa.DateTime(), nullable=True),
        sa.Column("source_last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("source_last_error", sa.Text(), nullable=True),
        sa.Column(
            "alert_threshold_days",
            sa.Integer(),
            nullable=False,
            server_default="14",
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "idx_manager_cert_enabled", "manager_certificates", ["enabled"],
    )
    op.create_index(
        "idx_manager_cert_source_path", "manager_certificates", ["source_path"],
    )

    op.create_table(
        "manager_cert_deployments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("certificate_id", sa.Integer(), nullable=False),
        sa.Column("host_id", sa.Integer(), nullable=False),
        # Empty string means "default host target". It avoids MySQL's
        # UNIQUE-with-NULL behaviour, where multiple NULL target_name rows
        # would be allowed for the same certificate/host pair.
        sa.Column(
            "target_name",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
        sa.Column("deployed_fingerprint_sha256", sa.String(length=64), nullable=True),
        sa.Column("deployed_not_after", sa.DateTime(), nullable=True),
        sa.Column("last_check_at", sa.DateTime(), nullable=True),
        sa.Column("last_check_error", sa.Text(), nullable=True),
        sa.Column("last_deploy_at", sa.DateTime(), nullable=True),
        sa.Column("last_deploy_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_deploy_error", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["certificate_id"],
            ["manager_certificates.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["host_id"],
            ["manager_hosts.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "certificate_id",
            "host_id",
            "target_name",
            name="uk_manager_cert_deployment_target",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "idx_manager_cert_deploy_cert",
        "manager_cert_deployments",
        ["certificate_id"],
    )
    op.create_index(
        "idx_manager_cert_deploy_host",
        "manager_cert_deployments",
        ["host_id"],
    )
    op.create_index(
        "idx_manager_cert_deploy_status",
        "manager_cert_deployments",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_manager_cert_deploy_status",
        table_name="manager_cert_deployments",
    )
    op.drop_index(
        "idx_manager_cert_deploy_host",
        table_name="manager_cert_deployments",
    )
    op.drop_index(
        "idx_manager_cert_deploy_cert",
        table_name="manager_cert_deployments",
    )
    op.drop_table("manager_cert_deployments")
    op.drop_index("idx_manager_cert_source_path", table_name="manager_certificates")
    op.drop_index("idx_manager_cert_enabled", table_name="manager_certificates")
    op.drop_table("manager_certificates")
