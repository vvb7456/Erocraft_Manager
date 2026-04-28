"""drop manager_host_tunnels.cloudflared_status

Single source of truth for "is cloudflared running" is the agent's live
status reply, not a DB cache. The DB only stores what we have told CF
(cf_tunnel_id, cf_config_version, cf_tunnel_secret_enc, etc).
See docs/CF_TUNNEL_PSEUDOCODE.md.

Revision ID: 20260429_0009
Revises: 20260428_0008
Create Date: 2026-04-29
"""
from __future__ import annotations

from alembic import op


revision = "20260429_0009"
down_revision = "20260428_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("manager_host_tunnels") as batch:
        batch.drop_column("cloudflared_status")


def downgrade() -> None:
    raise NotImplementedError("downgrade not supported")
