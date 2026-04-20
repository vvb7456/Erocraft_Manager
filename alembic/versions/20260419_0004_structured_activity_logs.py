"""Add structured activity log detail fields."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260419_0004"
down_revision = "20260419_0003"
branch_labels = None
depends_on = None


def _columns(bind: sa.Connection, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, "manager_activity_logs")
    op.execute(sa.text("DELETE FROM manager_activity_logs"))
    if "detail_key" not in columns:
        op.add_column("manager_activity_logs", sa.Column("detail_key", sa.String(length=120), nullable=True))
    if "detail_params" not in columns:
        op.add_column("manager_activity_logs", sa.Column("detail_params", sa.Text(), nullable=True))
    if "details" in columns:
        op.drop_column("manager_activity_logs", "details")


def downgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, "manager_activity_logs")
    if "details" not in columns:
        op.add_column("manager_activity_logs", sa.Column("details", sa.Text(), nullable=True))
    if "detail_params" in columns:
        op.drop_column("manager_activity_logs", "detail_params")
    if "detail_key" in columns:
        op.drop_column("manager_activity_logs", "detail_key")
