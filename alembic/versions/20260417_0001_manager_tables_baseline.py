"""Ensure manager-owned baseline tables exist."""

from __future__ import annotations

from collections.abc import Iterable

from alembic import op
import sqlalchemy as sa

revision = "20260417_0001"
down_revision = None
branch_labels = None
depends_on = None


def _table_names(bind: sa.Connection) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _index_names(bind: sa.Connection, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def _ensure_indexes(
    bind: sa.Connection,
    table_name: str,
    indexes: Iterable[tuple[str, list[str]]],
) -> None:
    if table_name not in _table_names(bind):
        return
    existing = _index_names(bind, table_name)
    for index_name, columns in indexes:
        if index_name not in existing:
            op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)

    if "manager_server_meta" not in tables:
        op.create_table(
            "manager_server_meta",
            sa.Column("server_id", sa.Integer(), nullable=False),
            sa.Column("expiration_date", sa.Date(), nullable=True),
            sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("server_id"),
        )

    if "manager_activity_logs" not in tables:
        op.create_table(
            "manager_activity_logs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("timestamp", sa.TIMESTAMP(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("actor", sa.String(length=100), nullable=False),
            sa.Column("action", sa.String(length=100), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("details", sa.Text(), nullable=True),
        )

    _ensure_indexes(
        bind,
        "manager_activity_logs",
        (
            ("idx_timestamp", ["timestamp"]),
            ("idx_actor", ["actor"]),
            ("idx_action", ["action"]),
        ),
    )

    if "manager_system_settings" not in tables:
        op.create_table(
            "manager_system_settings",
            sa.Column("key", sa.String(length=64), nullable=False),
            sa.Column("category", sa.String(length=32), nullable=False),
            sa.Column("value_text", sa.Text(), nullable=True),
            sa.Column("value_encrypted", sa.Text(), nullable=True),
            sa.Column("value_type", sa.String(length=16), nullable=False, server_default="string"),
            sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
            sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("key"),
        )

    _ensure_indexes(
        bind,
        "manager_system_settings",
        (("idx_category", ["category"]),),
    )


def downgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)

    if "manager_system_settings" in tables:
        if "idx_category" in _index_names(bind, "manager_system_settings"):
            op.drop_index("idx_category", table_name="manager_system_settings")
        op.drop_table("manager_system_settings")

    if "manager_activity_logs" in tables:
        for index_name in ("idx_timestamp", "idx_actor", "idx_action"):
            if index_name in _index_names(bind, "manager_activity_logs"):
                op.drop_index(index_name, table_name="manager_activity_logs")
        op.drop_table("manager_activity_logs")

    if "manager_server_meta" in tables:
        op.drop_table("manager_server_meta")
