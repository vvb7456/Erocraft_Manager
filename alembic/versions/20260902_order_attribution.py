"""Add channel order attribution columns to manager_billing_orders.

Enables order traceability for e-commerce (Taobao/Xianyu) and manual server
creation/renewals by recording channel, external_order_id, operator, and note.
"""

from __future__ import annotations

from alembic import op


revision = "20260902_order_attr"
down_revision = "20260803_mon_tune"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
ALTER TABLE `manager_billing_orders`
  ADD COLUMN `channel` varchar(32) NOT NULL DEFAULT 'alipay' AFTER `kind`,
  ADD COLUMN `external_order_id` varchar(64) DEFAULT NULL AFTER `channel`,
  ADD COLUMN `operator` varchar(100) NOT NULL DEFAULT 'system' AFTER `external_order_id`,
  ADD COLUMN `channel_note` varchar(255) DEFAULT NULL AFTER `operator`,
  ADD KEY `idx_billing_orders_channel` (`channel`),
  ADD UNIQUE KEY `uq_billing_orders_channel_external` (`channel`, `external_order_id`)
        """
    )


def downgrade() -> None:
    op.execute(
        """
ALTER TABLE `manager_billing_orders`
  DROP KEY `uq_billing_orders_channel_external`,
  DROP KEY `idx_billing_orders_channel`,
  DROP COLUMN `channel_note`,
  DROP COLUMN `operator`,
  DROP COLUMN `external_order_id`,
  DROP COLUMN `channel`
        """
    )
