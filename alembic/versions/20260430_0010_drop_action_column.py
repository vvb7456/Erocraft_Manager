"""drop manager_activity_logs.action column

`action` was a fine-grained operation tag that was always derived from the
caller, while `category` is the aggregated bucket actually consumed by the UI.
The frontend only renders/filters by category, so action is dropped entirely.
See docs/ARCHITECTURE_V3.md and audit.py.

Revision ID: 20260430_0010
Revises: 20260429_0009
Create Date: 2026-04-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260430_0010"
down_revision = "20260429_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("manager_activity_logs") as batch:
        batch.drop_index("idx_action")
        batch.drop_column("action")


def downgrade() -> None:
    with op.batch_alter_table("manager_activity_logs") as batch:
        batch.add_column(sa.Column("action", sa.String(length=100), nullable=False, server_default=""))
        batch.create_index("idx_action", ["action"])
