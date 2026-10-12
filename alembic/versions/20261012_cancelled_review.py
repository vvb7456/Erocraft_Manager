"""已取消或关闭订单的到账审核不占用新订单名额。"""

from alembic import op


revision = "20261012_cancel_review"
down_revision = "20261012_wechat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
ALTER TABLE `manager_billing_orders`
  DROP INDEX `uk_billing_orders_active_user`,
  DROP COLUMN `active_user_lock`,
  ADD COLUMN `active_user_lock` int(11) GENERATED ALWAYS AS (
    CASE WHEN `status` IN ('pending', 'processing')
      OR (`status` = 'manual_review' AND `cancelled_at` IS NULL AND `closed_at` IS NULL)
    THEN `user_id` END
  ) VIRTUAL,
  ADD UNIQUE KEY `uk_billing_orders_active_user` (`active_user_lock`)
        """
    )


def downgrade() -> None:
    op.execute(
        """
ALTER TABLE `manager_billing_orders`
  DROP INDEX `uk_billing_orders_active_user`,
  DROP COLUMN `active_user_lock`,
  ADD COLUMN `active_user_lock` int(11) GENERATED ALWAYS AS (
    CASE WHEN `status` IN ('pending', 'processing', 'manual_review') THEN `user_id` END
  ) VIRTUAL,
  ADD UNIQUE KEY `uk_billing_orders_active_user` (`active_user_lock`)
        """
    )
