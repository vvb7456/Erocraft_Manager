"""migrate_node_id_to_host_id

Replace ``node_id`` with ``host_id`` across the monitoring tables so that
non-wings hosts (which lack a ``pterodactyl_node_id``) can store metrics
and alerts.
"""

revision = 'ea00339c95b9'
down_revision = '20260425_0006'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


def _add_host_id(table: str) -> None:
    op.add_column(table, sa.Column("host_id", sa.BigInteger(), nullable=True))


def _drop_node_id_fk(table: str, fk_name: str) -> None:
    try:
        op.drop_constraint(fk_name, table, type_="foreignkey")
    except Exception:
        pass


def _backfill_host_id(table: str, join_on: str) -> None:
    op.execute(sa.text(f"""
        UPDATE {table} t
        JOIN manager_hosts h ON h.pterodactyl_node_id = t.{join_on}
        SET t.host_id = h.id
    """))


def upgrade() -> None:
    # ── manager_node_metrics ──────────────────────────────────────────
    _add_host_id("manager_node_metrics")
    op.create_index("idx_nm_host_ts", "manager_node_metrics", ["host_id", "ts"])
    _backfill_host_id("manager_node_metrics", "node_id")

    _drop_node_id_fk("manager_node_metrics", "manager_node_metrics_ibfk_1")
    op.drop_index("idx_nm_node_ts", table_name="manager_node_metrics")
    op.drop_column("manager_node_metrics", "node_id")
    op.alter_column("manager_node_metrics", "host_id",
                    existing_type=sa.BigInteger(), nullable=False)

    # ── manager_node_alerts ───────────────────────────────────────────
    _add_host_id("manager_node_alerts")
    op.create_index("idx_na_host_active", "manager_node_alerts", ["host_id", "resolved_at"])
    _backfill_host_id("manager_node_alerts", "node_id")

    _drop_node_id_fk("manager_node_alerts", "manager_node_alerts_ibfk_1")
    op.drop_index("idx_na_node_active", table_name="manager_node_alerts")
    op.drop_column("manager_node_alerts", "node_id")
    op.alter_column("manager_node_alerts", "host_id",
                    existing_type=sa.BigInteger(), nullable=False)

    # ── manager_probe_results ─────────────────────────────────────────
    _add_host_id("manager_probe_results")
    op.create_index("idx_pr_host_ts", "manager_probe_results", ["host_id", "ts"])
    # Backfill from source field (format: "agent:<node_id>") and
    # probe_name field (format: "wings_pub_<node_id>").
    op.execute(sa.text("""
        UPDATE manager_probe_results pr
        JOIN manager_hosts h ON (
            h.pterodactyl_node_id = CAST(NULLIF(
                SUBSTRING_INDEX(pr.source, ':', -1), pr.source
            ) AS UNSIGNED)
            OR h.pterodactyl_node_id = CAST(NULLIF(
                SUBSTRING_INDEX(pr.probe_name, '_', -1), pr.probe_name
            ) AS UNSIGNED)
        )
        SET pr.host_id = h.id
    """))
    # Orphan probes (no matching host) get host_id=0 so we can make it NOT NULL.
    op.execute(sa.text(
        "UPDATE manager_probe_results SET host_id = 0 WHERE host_id IS NULL"
    ))
    op.alter_column("manager_probe_results", "host_id",
                    existing_type=sa.BigInteger(), nullable=False)


def downgrade() -> None:
    # ── manager_node_metrics ──────────────────────────────────────────
    op.add_column("manager_node_metrics",
                  sa.Column("node_id", mysql.INTEGER(unsigned=True), nullable=True))
    op.create_index("idx_nm_node_ts", "manager_node_metrics", ["node_id", "ts"])
    op.execute(sa.text("""
        UPDATE manager_node_metrics m
        JOIN manager_hosts h ON h.id = m.host_id
        SET m.node_id = h.pterodactyl_node_id
    """))
    op.create_foreign_key(
        "manager_node_metrics_ibfk_1", "manager_node_metrics", "nodes",
        ["node_id"], ["id"], ondelete="CASCADE",
    )
    op.drop_index("idx_nm_host_ts", table_name="manager_node_metrics")
    op.drop_column("manager_node_metrics", "host_id")
    op.alter_column("manager_node_metrics", "node_id",
                    existing_type=mysql.INTEGER(unsigned=True), nullable=False)

    # ── manager_node_alerts ───────────────────────────────────────────
    op.add_column("manager_node_alerts",
                  sa.Column("node_id", mysql.INTEGER(unsigned=True), nullable=True))
    op.create_index("idx_na_node_active", "manager_node_alerts", ["node_id", "resolved_at"])
    op.execute(sa.text("""
        UPDATE manager_node_alerts a
        JOIN manager_hosts h ON h.id = a.host_id
        SET a.node_id = h.pterodactyl_node_id
    """))
    op.create_foreign_key(
        "manager_node_alerts_ibfk_1", "manager_node_alerts", "nodes",
        ["node_id"], ["id"], ondelete="CASCADE",
    )
    op.drop_index("idx_na_host_active", table_name="manager_node_alerts")
    op.drop_column("manager_node_alerts", "host_id")
    op.alter_column("manager_node_alerts", "node_id",
                    existing_type=mysql.INTEGER(unsigned=True), nullable=True)

    # ── manager_probe_results ─────────────────────────────────────────
    op.drop_index("idx_pr_host_ts", table_name="manager_probe_results")
    op.drop_column("manager_probe_results", "host_id")
