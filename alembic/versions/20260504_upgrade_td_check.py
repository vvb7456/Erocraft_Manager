"""Allow total_days = 0 for upgrade orders.

Upgrade orders charge prorated price difference between old and new plan
over the remaining days, without adding net-new days. The old CHECK
``total_days > 0`` blocked this; relaxed to ``>= 0``.
"""

from __future__ import annotations

from alembic import op


revision = "20260504_upgrade_td_check"
down_revision = "20260503_billing_upgrade_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE manager_billing_orders "
        "DROP CONSTRAINT chk_billing_orders_total_days_pos"
    )
    op.execute(
        "ALTER TABLE manager_billing_orders "
        "ADD CONSTRAINT chk_billing_orders_total_days_pos "
        "CHECK (total_days >= 0)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE manager_billing_orders "
        "DROP CONSTRAINT chk_billing_orders_total_days_pos"
    )
    op.execute(
        "ALTER TABLE manager_billing_orders "
        "ADD CONSTRAINT chk_billing_orders_total_days_pos "
        "CHECK (total_days > 0)"
    )
