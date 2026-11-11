"""新增兑换码（批次、导出记录、兑换码）数据表。"""

from __future__ import annotations

from alembic import op


revision = "20261111_redemption_codes"
down_revision = "20261105_remove_server_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE `manager_redemption_batches` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL,
  `source` varchar(16) NOT NULL DEFAULT 'manual',
  `spec_key` varchar(64) DEFAULT NULL,
  `plan_id` bigint(20) DEFAULT NULL,
  `days` int(11) NOT NULL,
  `amount_fen` int(11) NOT NULL,
  `channel` varchar(32) NOT NULL DEFAULT 'taobao',
  `quantity` int(11) NOT NULL DEFAULT 0,
  `expires_at` datetime DEFAULT NULL,
  `created_by` int(11) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_redemption_batch_spec` (`spec_key`),
  KEY `idx_redemption_batch_plan` (`plan_id`),
  KEY `idx_redemption_batch_source` (`source`),
  CONSTRAINT `fk_redemption_batch_plan` FOREIGN KEY (`plan_id`) REFERENCES `manager_billing_plans` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_redemption_exports` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `batch_id` bigint(20) NOT NULL,
  `quantity` int(11) NOT NULL,
  `created_by` int(11) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_redemption_export_batch` (`batch_id`),
  CONSTRAINT `fk_redemption_export_batch` FOREIGN KEY (`batch_id`) REFERENCES `manager_redemption_batches` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_redemption_codes` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `code` varchar(40) NOT NULL,
  `batch_id` bigint(20) NOT NULL,
  `plan_id` bigint(20) DEFAULT NULL,
  `days` int(11) NOT NULL,
  `amount_fen` int(11) NOT NULL,
  `channel` varchar(32) NOT NULL DEFAULT 'taobao',
  `expires_at` datetime DEFAULT NULL,
  `external_request_id` varchar(64) DEFAULT NULL,
  `external_order_id` varchar(64) DEFAULT NULL,
  `status` varchar(16) NOT NULL DEFAULT 'unused',
  `export_id` bigint(20) DEFAULT NULL,
  `redeemed_by` int(11) DEFAULT NULL,
  `redeemed_at` datetime DEFAULT NULL,
  `order_id` bigint(20) DEFAULT NULL,
  `target_server_id` int(11) DEFAULT NULL,
  `voided_by` int(11) DEFAULT NULL,
  `voided_at` datetime DEFAULT NULL,
  `void_reason` varchar(255) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_redemption_code` (`code`),
  UNIQUE KEY `uk_redemption_code_order` (`order_id`),
  KEY `idx_redemption_code_batch` (`batch_id`),
  KEY `idx_redemption_code_plan` (`plan_id`),
  KEY `idx_redemption_code_status` (`status`),
  KEY `idx_redemption_code_export` (`export_id`),
  KEY `idx_redemption_code_redeemed_by` (`redeemed_by`),
  KEY `idx_redemption_code_ext_req` (`channel`, `external_request_id`),
  KEY `idx_redemption_code_ext_ord` (`external_order_id`),
  CONSTRAINT `fk_redemption_code_batch` FOREIGN KEY (`batch_id`) REFERENCES `manager_redemption_batches` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_redemption_code_plan` FOREIGN KEY (`plan_id`) REFERENCES `manager_billing_plans` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_redemption_code_export` FOREIGN KEY (`export_id`) REFERENCES `manager_redemption_exports` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_redemption_code_order` FOREIGN KEY (`order_id`) REFERENCES `manager_billing_orders` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        "ALTER TABLE `manager_billing_orders` DROP CONSTRAINT `chk_billing_orders_total_fen_pos`"
    )
    op.execute(
        """
ALTER TABLE `manager_billing_orders`
  ADD CONSTRAINT `chk_billing_orders_total_fen_pos`
  CHECK ((`channel` = '' AND `total_fen` > 0) OR (`channel` <> '' AND `total_fen` >= 0))
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE `manager_billing_orders` DROP CONSTRAINT `chk_billing_orders_total_fen_pos`"
    )
    op.execute(
        """
ALTER TABLE `manager_billing_orders`
  ADD CONSTRAINT `chk_billing_orders_total_fen_pos` CHECK (`total_fen` > 0)
        """
    )
    op.execute("DROP TABLE IF EXISTS `manager_redemption_codes`")
    op.execute("DROP TABLE IF EXISTS `manager_redemption_exports`")
    op.execute("DROP TABLE IF EXISTS `manager_redemption_batches`")
