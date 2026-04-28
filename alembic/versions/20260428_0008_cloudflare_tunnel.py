"""cloudflare tunnel registry: host tunnels, server tunnels, orphan resources.

See ``docs/CLOUDFLARE_TUNNEL_DESIGN.md`` for the full design.

Three new tables:

* ``manager_host_tunnels`` — 1:1 with ``manager_hosts``. Holds the CF account
  binding (token, zone) and the cloudflared install state for that host. The
  CF tunnel UUID + secret live here once the tunnel has been provisioned.

* ``manager_server_tunnels`` — 1:1 with ``panel.servers`` (no FK across
  schemas; see design §2.2). One row per server that has tunnel access
  enabled by the user. Stores the user-facing hostname, the CF DNS record
  id (so we can delete it later), and the upstream port snapshot.

* ``manager_orphan_resources`` — bookkeeping for the reconciler (§8b.4).
  When a CF tunnel or DNS record exists on Cloudflare but no DB row claims
  it (e.g. due to a half-completed install or out-of-band deletion in the
  Dashboard), the reconciler records it here so an admin can review +
  delete or ignore via the cleanup UI.

Revision ID: 20260428_0008
Revises: 20260428_0007
Create Date: 2026-04-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260428_0008"
down_revision = "20260428_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manager_host_tunnels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "host_id",
            sa.Integer(),
            sa.ForeignKey("manager_hosts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cf_account_id", sa.String(length=64), nullable=False),
        sa.Column("cf_api_token_enc", sa.Text(), nullable=False),
        sa.Column("cf_zone_id", sa.String(length=64), nullable=False),
        sa.Column("cf_zone_name", sa.String(length=255), nullable=False),
        sa.Column("cf_tunnel_id", sa.String(length=64), nullable=True),
        sa.Column("cf_tunnel_name", sa.String(length=255), nullable=True),
        sa.Column("cf_tunnel_secret_enc", sa.Text(), nullable=True),
        sa.Column("cloudflared_version", sa.String(length=32), nullable=True),
        sa.Column(
            "cloudflared_status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("cf_config_version", sa.Integer(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("host_id", name="uk_host_tunnel_host"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )

    op.create_table(
        "manager_server_tunnels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column(
            "host_tunnel_id",
            sa.Integer(),
            sa.ForeignKey("manager_host_tunnels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("custom_subdomain", sa.String(length=64), nullable=True),
        sa.Column("upstream_port", sa.Integer(), nullable=False),
        sa.Column(
            "upstream_scheme",
            sa.String(length=8),
            nullable=False,
            server_default="http",
        ),
        sa.Column("cf_dns_record_id", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="provisioning",
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("enabled_at", sa.DateTime(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
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
        sa.UniqueConstraint("server_id", name="uk_server_tunnel_server"),
        sa.UniqueConstraint("hostname", name="uk_server_tunnel_hostname"),
        sa.Index("ix_server_tunnel_status", "status"),
        sa.Index("ix_server_tunnel_host_tunnel", "host_tunnel_id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )

    op.create_table(
        "manager_orphan_resources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # 'tunnel' or 'dns_record'
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("cf_account_id", sa.String(length=64), nullable=False),
        sa.Column("cf_zone_id", sa.String(length=64), nullable=True),
        sa.Column("cf_resource_id", sa.String(length=64), nullable=False),
        sa.Column("cf_resource_name", sa.String(length=255), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "resource_type",
            "cf_resource_id",
            name="uk_orphan_resource",
        ),
        sa.Index("ix_orphan_type", "resource_type"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("manager_orphan_resources")
    op.drop_table("manager_server_tunnels")
    op.drop_table("manager_host_tunnels")
