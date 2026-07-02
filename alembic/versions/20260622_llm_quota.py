"""LLM free quota: plan columns + server key table.

Adds:

* ``manager_billing_plans.llm_enabled`` / ``llm_quota_grant`` /
  ``llm_model_limits`` — per-plan LLM free quota configuration.
* ``manager_server_llm_keys`` — one row per server holding a NewAPI token
  (plaintext key, quota grant/used, status, staggered monthly reset day).

The key follows server status (not expiration) and its quota resets
monthly on ``reset_day`` (the day-of-month it was provisioned, clamped to
28), spreading reset load across the month.
"""

from __future__ import annotations

from alembic import op


revision = "20260622_llm"
down_revision = "20260625_notify_retry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── manager_billing_plans: LLM quota columns ─────────────────────────
    op.execute(
        """
ALTER TABLE `manager_billing_plans`
  ADD COLUMN `llm_enabled` tinyint(1) NOT NULL DEFAULT 0 AFTER `linked_plan_id`,
  ADD COLUMN `llm_quota_grant` int(11) NOT NULL DEFAULT 0 AFTER `llm_enabled`,
  ADD COLUMN `llm_model_limits` varchar(255) DEFAULT NULL AFTER `llm_quota_grant`
        """
    )

    # ── manager_server_llm_keys ──────────────────────────────────────────
    op.execute(
        """
CREATE TABLE `manager_server_llm_keys` (
  `server_id` int(10) unsigned NOT NULL,
  `user_id` int(10) unsigned NOT NULL,
  `newapi_token_id` int(11) NOT NULL,
  `api_key` varchar(128) NOT NULL,
  `quota_grant` int(11) NOT NULL DEFAULT 0,
  `quota_used` int(11) NOT NULL DEFAULT 0,
  `quota_available` int(11) NOT NULL DEFAULT 0,
  `model_limits` varchar(255) DEFAULT NULL,
  `status` varchar(16) NOT NULL DEFAULT 'active',
  `last_reset_at` datetime DEFAULT NULL,
  `reset_day` tinyint(4) NOT NULL DEFAULT 1,
  `last_synced_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`server_id`),
  KEY `idx_llm_keys_user` (`user_id`),
  KEY `idx_llm_keys_status` (`status`),
  CONSTRAINT `fk_llm_keys_server` FOREIGN KEY (`server_id`) REFERENCES `servers` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS `manager_server_llm_keys`")
    op.execute(
        """
ALTER TABLE `manager_billing_plans`
  DROP COLUMN `llm_model_limits`,
  DROP COLUMN `llm_quota_grant`,
  DROP COLUMN `llm_enabled`
        """
    )
