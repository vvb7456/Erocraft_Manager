"""install-notify exponential-backoff retry.

Adds two columns to ``manager_server_meta`` so the per-minute
``server_install_notify`` job can back off failed sends on the same
exponential schedule the billing apply engine uses
(``RETRY_DELAYS = [1m, 5m, 15m, 1h, 4h]``):

* ``install_notify_attempts`` — count of failed send attempts.
* ``install_notify_next_at`` — earliest time the scan should retry.

Without these a recipient the SMTP relay permanently rejects (e.g. an
invalid address such as ``user@qq.con`` returning QQ's ``559 invaddr
reject``) would be retried every minute, spamming the audit log with one
``email_failed`` entry per tick. With them the row is retried at most 5
times on an expanding schedule, then finalized as given-up.
"""

from __future__ import annotations

from alembic import op


revision = "20260625_notify_retry"
down_revision = "20260622_llm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
ALTER TABLE `manager_server_meta`
  ADD COLUMN `install_notify_attempts` int(11) NOT NULL DEFAULT 0
      AFTER `install_notified_at`,
  ADD COLUMN `install_notify_next_at` datetime DEFAULT NULL
      AFTER `install_notify_attempts`
        """
    )


def downgrade() -> None:
    op.execute(
        """
ALTER TABLE `manager_server_meta`
  DROP COLUMN `install_notify_next_at`,
  DROP COLUMN `install_notify_attempts`
        """
    )
