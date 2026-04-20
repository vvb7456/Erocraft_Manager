"""Add account self-service token tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260419_0002"
down_revision = "20260417_0001"
branch_labels = None
depends_on = None


def _table_names(bind: sa.Connection) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _index_names(bind: sa.Connection, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)

    if "manager_password_resets" not in tables:
        op.create_table(
            "manager_password_resets",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("token", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("used_at", sa.DateTime(), nullable=True),
        )

    if "manager_password_resets" in _table_names(bind):
        if "idx_pw_reset_user_id" not in _index_names(bind, "manager_password_resets"):
            op.create_index("idx_pw_reset_user_id", "manager_password_resets", ["user_id"])

    if "manager_email_changes" not in tables:
        op.create_table(
            "manager_email_changes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("new_email", sa.String(length=255), nullable=False),
            sa.Column("token", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        )

    if "manager_email_changes" in _table_names(bind):
        if "idx_email_change_user_id" not in _index_names(bind, "manager_email_changes"):
            op.create_index("idx_email_change_user_id", "manager_email_changes", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)

    if "manager_email_changes" in tables:
        if "idx_email_change_user_id" in _index_names(bind, "manager_email_changes"):
            op.drop_index("idx_email_change_user_id", table_name="manager_email_changes")
        op.drop_table("manager_email_changes")

    if "manager_password_resets" in tables:
        if "idx_pw_reset_user_id" in _index_names(bind, "manager_password_resets"):
            op.drop_index("idx_pw_reset_user_id", table_name="manager_password_resets")
        op.drop_table("manager_password_resets")
