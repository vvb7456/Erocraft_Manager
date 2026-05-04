"""Decouple billing orders from plans: plan_id NULL + ON DELETE SET NULL.

Orders carry a complete ``plan_snapshot`` (JSON) frozen at creation time,
so the live ``plan_id`` is only a soft pointer used for "orders by plan"
analytics. Allowing it to go NULL means admins can hard-delete a plan
even if historical orders reference it; the orders keep their snapshot
and remain fully renderable / auditable.
"""

from __future__ import annotations

from alembic import op


revision = "20260502_orders_plan_decouple"
down_revision = "20260501_billing_plan_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the existing RESTRICT FK, make column nullable, recreate FK with
    # ON DELETE SET NULL. Keep the same constraint + index names for clarity.
    op.execute(
        "ALTER TABLE manager_billing_orders "
        "DROP FOREIGN KEY fk_billing_orders_plan"
    )
    op.execute(
        "ALTER TABLE manager_billing_orders "
        "MODIFY COLUMN plan_id BIGINT NULL"
    )
    op.execute(
        "ALTER TABLE manager_billing_orders "
        "ADD CONSTRAINT fk_billing_orders_plan "
        "FOREIGN KEY (plan_id) REFERENCES manager_billing_plans(id) "
        "ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE manager_billing_orders "
        "DROP FOREIGN KEY fk_billing_orders_plan"
    )
    # Restore NOT NULL — will fail if any rows have plan_id IS NULL.
    op.execute(
        "ALTER TABLE manager_billing_orders "
        "MODIFY COLUMN plan_id BIGINT NOT NULL"
    )
    op.execute(
        "ALTER TABLE manager_billing_orders "
        "ADD CONSTRAINT fk_billing_orders_plan "
        "FOREIGN KEY (plan_id) REFERENCES manager_billing_plans(id)"
    )
