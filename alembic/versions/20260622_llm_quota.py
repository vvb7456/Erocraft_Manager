"""LLM subscription: plan columns + server key table.

Adds:

* ``manager_billing_plans.llm_enabled`` / ``llm_quota_grant`` /
  ``newapi_plan_id`` / ``llm_group`` — per-plan LLM subscription
  configuration. ``llm_quota_grant`` maps to NewAPI SubscriptionPlan
  ``TotalAmount``; ``llm_group`` is the NewAPI group name whose channel
  bindings determine accessible models (method 3A); ``newapi_plan_id``
  is the synced NewAPI SubscriptionPlan id.
* ``manager_server_llm_keys`` — one row per server holding a NewAPI
  per-server user (``newapi_user_id``), their access token, a bound
  subscription (``newapi_subscription_id``), and the plaintext API key
  (``api_key``). Quota enforcement is entirely via the NewAPI
  subscription (``subscription_only`` billing preference); the token is
  set to ``unlimited_quota``.
"""

from __future__ import annotations

from alembic import op


revision = "20260622_llm"
down_revision = "20260625_notify_retry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── manager_billing_plans: LLM subscription columns ──────────────────
    op.execute(
        """
ALTER TABLE `manager_billing_plans`
  ADD COLUMN `llm_enabled` tinyint(1) NOT NULL DEFAULT 0 AFTER `linked_plan_id`,
  ADD COLUMN `llm_quota_grant` int(11) NOT NULL DEFAULT 0 AFTER `llm_enabled`,
  ADD COLUMN `newapi_plan_id` bigint DEFAULT NULL AFTER `llm_quota_grant`,
  ADD COLUMN `llm_group` varchar(64) DEFAULT NULL AFTER `newapi_plan_id`
        """
    )

    # ── manager_server_llm_keys ──────────────────────────────────────────
    op.execute(
        """
CREATE TABLE `manager_server_llm_keys` (
  `server_id` int(10) unsigned NOT NULL,
  `user_id` int(10) unsigned NOT NULL,
  `newapi_user_id` int(11) NOT NULL DEFAULT 0,
  `newapi_user_access_token` varchar(128) NOT NULL DEFAULT '',
  `newapi_user_password` varchar(64) NOT NULL DEFAULT '',
  `newapi_subscription_id` int(11) NOT NULL DEFAULT 0,
  `newapi_plan_id` bigint DEFAULT NULL,
  `newapi_token_id` int(11) NOT NULL,
  `api_key` varchar(128) NOT NULL,
  `status` varchar(16) NOT NULL DEFAULT 'active',
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
  DROP COLUMN `llm_group`,
  DROP COLUMN `newapi_plan_id`,
  DROP COLUMN `llm_quota_grant`,
  DROP COLUMN `llm_enabled`
        """
    )
