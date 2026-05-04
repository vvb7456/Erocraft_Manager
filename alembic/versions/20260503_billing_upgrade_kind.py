"""Add 'upgrade' to billing order kind enum.

Upgrade orders charge a prorated diff_fen to switch a server's plan to
a higher-priced plan with the same egg, without touching expiration_date.
"""

from __future__ import annotations

from alembic import op


revision = "20260503_billing_upgrade_kind"
down_revision = "20260502_orders_plan_decouple"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE manager_billing_orders "
        "MODIFY COLUMN kind ENUM('renew','new_purchase','upgrade') NOT NULL"
    )
    op.execute(
        "ALTER TABLE manager_billing_order_effects "
        "MODIFY COLUMN effect_type ENUM('renew','new_purchase','upgrade') NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE manager_billing_order_effects "
        "MODIFY COLUMN effect_type ENUM('renew','new_purchase') NOT NULL"
    )
    op.execute(
        "ALTER TABLE manager_billing_orders "
        "MODIFY COLUMN kind ENUM('renew','new_purchase') NOT NULL"
    )
