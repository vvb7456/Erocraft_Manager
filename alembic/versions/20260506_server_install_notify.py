"""Add manager_server_meta.install_notified_at for one-shot install email.

Used by the ``server_install_notify`` job to send an "install complete"
email exactly once per server, on **first** install only. Reinstalls and
update-triggered reinstalls are skipped because this column stays set
across them (only ``servers.installed_at`` gets cleared, not this).

Backfill: for every existing server that already has ``installed_at``
set, copy it into ``install_notified_at`` so we don't email everyone
when the job first runs after deploy.
"""

from __future__ import annotations

from alembic import op


revision = "20260506_server_install_notify"
down_revision = "20260429_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE manager_server_meta "
        "ADD COLUMN install_notified_at DATETIME NULL"
    )

    # Backfill 1: existing meta rows whose server is already installed.
    op.execute(
        """
        UPDATE manager_server_meta m
        JOIN servers s ON s.id = m.server_id
        SET m.install_notified_at = s.installed_at
        WHERE s.installed_at IS NOT NULL
          AND m.install_notified_at IS NULL
        """
    )

    # Backfill 2: insert meta rows for installed servers that have none yet,
    # so the next install_notified_at IS NULL scan won't pick them up.
    op.execute(
        """
        INSERT INTO manager_server_meta (server_id, install_notified_at)
        SELECT s.id, s.installed_at
        FROM servers s
        LEFT JOIN manager_server_meta m ON m.server_id = s.id
        WHERE m.server_id IS NULL
          AND s.installed_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE manager_server_meta DROP COLUMN install_notified_at"
    )
