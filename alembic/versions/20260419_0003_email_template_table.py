"""Add DB-backed email template table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260419_0003"
down_revision = "20260419_0002"
branch_labels = None
depends_on = None


def _table_names(bind: sa.Connection) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    if "manager_email_templates" in _table_names(bind):
        return

    op.create_table(
        "manager_email_templates",
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("template_key"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "manager_email_templates" in _table_names(bind):
        op.drop_table("manager_email_templates")
