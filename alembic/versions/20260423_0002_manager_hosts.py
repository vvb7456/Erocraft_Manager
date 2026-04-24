"""manager_hosts unified host registry — PR-B step B1.

Adds the ``manager_hosts`` table and backfills one ``kind='wings_node'``
row per existing entry in ``manager_node_meta`` that has both
``agent_endpoint`` and ``agent_token_encrypted`` populated. The encrypted
token is copied verbatim — both columns store Fernet ciphertext over the
same ``MANAGER_SECRET_KEY``, so no decrypt/re-encrypt round-trip is
needed.

This step is intentionally **additive only**: ``manager_node_meta``
remains in place. PR-B step B2 will switch every reader (agent_client,
admin_nodes, monitoring jobs) to ``manager_hosts`` and drop the legacy
table in a follow-up migration.

See ``docs/HOST_MANAGEMENT_DESIGN.md`` §4.1 for the schema rationale.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260423_0002"
down_revision = "20260421_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manager_hosts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("agent_url", sa.String(length=255), nullable=False),
        sa.Column("agent_token_enc", sa.Text(), nullable=False),
        sa.Column(
            "pterodactyl_node_id",
            mysql.INTEGER(unsigned=True),
            nullable=True,
        ),
        sa.Column("extra_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "inbound_reachable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_status_at", sa.DateTime(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["pterodactyl_node_id"], ["nodes.id"], ondelete="CASCADE",
        ),
        sa.UniqueConstraint("pterodactyl_node_id", name="uk_pterodactyl_node"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("idx_kind", "manager_hosts", ["kind"])
    op.create_index("idx_enabled", "manager_hosts", ["enabled"])

    # One-shot backfill: every wings node that already has agent metadata
    # gets a manager_hosts row (kind='wings_node'). Nodes without an agent
    # configured are skipped — admin will create them via the UI in PR-C.
    #
    # name <- panel.nodes.name (admin can rename later)
    # hostname <- panel.nodes.fqdn (used as agent's host label; not
    #             necessarily where the agent listens — agent_url carries
    #             the actual ingress URL)
    # agent_token_enc <- the existing Fernet ciphertext, used as-is
    op.execute(
        """
        INSERT INTO manager_hosts
          (name, kind, hostname, agent_url, agent_token_enc,
           pterodactyl_node_id, enabled, inbound_reachable,
           created_at, updated_at)
        SELECT
          n.name, 'wings_node', n.fqdn, m.agent_endpoint,
          m.agent_token_encrypted, m.node_id,
          1, 1, NOW(), NOW()
        FROM manager_node_meta m
        INNER JOIN nodes n ON n.id = m.node_id
        WHERE m.agent_endpoint IS NOT NULL
          AND m.agent_token_encrypted IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("idx_enabled", table_name="manager_hosts")
    op.drop_index("idx_kind", table_name="manager_hosts")
    op.drop_table("manager_hosts")
