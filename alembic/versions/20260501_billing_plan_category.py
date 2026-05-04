"""Add category_label to manager_billing_plans for grouping on /plans page.

The label is a free-form string (UI-driven, not a FK to a category table) so
admins can rename / regroup without DB migrations. Frontend buckets plans
sharing the same exact label into one section. ``NULL`` means "uncategorised"
and renders in a dedicated trailing section.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260501_billing_plan_category"
down_revision = "20260429_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "manager_billing_plans",
        sa.Column("category_label", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("manager_billing_plans", "category_label")
