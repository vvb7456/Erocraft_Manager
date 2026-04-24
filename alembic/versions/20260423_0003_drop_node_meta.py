"""drop manager_node_meta (superseded by manager_hosts)

Revision ID: 20260423_0003
Revises: 20260423_0002
Create Date: 2026-04-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260423_0003"
down_revision = "20260423_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop the legacy ``manager_node_meta`` table.

    Backfill into ``manager_hosts`` happened in migration 20260423_0002. By
    the time this revision applies, every wings_node integration the
    operator wants to keep already lives as a row in ``manager_hosts`` —
    the old per-node-id table is just stale duplicates of agent_url +
    Fernet ciphertext.

    No data preservation here: re-running the previous migration's
    backfill is the correct recovery path if something was missed.
    """
    op.drop_table("manager_node_meta")


def downgrade() -> None:
    """Recreate the legacy table empty.

    The downgrade does **not** repopulate from manager_hosts because that
    direction is only meaningful during pre-deployment rehearsal — once
    PR-B is in production any operator changes flow through manager_hosts
    and reverse-syncing them would just be lossy.
    """
    op.create_table(
        "manager_node_meta",
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("agent_endpoint", sa.String(length=200), nullable=True),
        sa.Column("agent_token_encrypted", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["node_id"], ["nodes.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("node_id"),
    )
