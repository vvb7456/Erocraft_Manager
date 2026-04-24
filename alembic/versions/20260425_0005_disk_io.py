"""add disk_read_bps and disk_write_bps to manager_node_metrics.

Revision ID: 20260425_0005
Revises: 20260424_0004
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260425_0005"
down_revision = "20260424_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "manager_node_metrics",
        sa.Column("disk_read_bps", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "manager_node_metrics",
        sa.Column("disk_write_bps", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("manager_node_metrics", "disk_write_bps")
    op.drop_column("manager_node_metrics", "disk_read_bps")
