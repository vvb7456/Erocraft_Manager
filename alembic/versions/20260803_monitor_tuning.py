"""Per-host monitoring pull tuning + availability sustain window.

Adds two columns to ``manager_host_alert_settings`` so operators can tune
the Manager -> Agent ``/v1/metrics`` pull behaviour per host. This is a
Manager-side (client) setting, not an agent config — the agent cannot
dictate how long the Manager is willing to wait. NULL on either column
means "inherit the code default" (``AGENT_PULL_TIMEOUT`` /
``AGENT_PULL_ATTEMPTS`` in ``app.jobs.tasks.monitoring``).

Motivation: cross-border hosts (e.g. Singapore from the Hangzhou console)
suffer 500 ms+ RTT and intermittent second-grade jitter. The previous
hard-coded 5 s timeout / 3 attempts caused repeated spurious
``node_offline critical`` alerts that self-resolved within one cycle.

* ``agent_pull_timeout`` — seconds the Manager waits for one attempt.
* ``agent_pull_attempts`` — total attempts before giving up (1 + retries).

This migration only adds the override columns. The sustain window for
availability alerts (``node_offline`` / ``agent_only_down``) reuses the
existing ``manager_host_alert_rules.sustain_min`` column — the defaults
table in ``app.core.alert_defaults`` is the only place that changes.
"""

from __future__ import annotations

from alembic import op


revision = "20260803_mon_tune"
down_revision = "20260718_agreements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
ALTER TABLE `manager_host_alert_settings`
  ADD COLUMN `agent_pull_timeout` float DEFAULT NULL
      AFTER `cooldown_min`,
  ADD COLUMN `agent_pull_attempts` int(11) DEFAULT NULL
      AFTER `agent_pull_timeout`
        """
    )


def downgrade() -> None:
    op.execute(
        """
ALTER TABLE `manager_host_alert_settings`
  DROP COLUMN `agent_pull_attempts`,
  DROP COLUMN `agent_pull_timeout`
        """
    )