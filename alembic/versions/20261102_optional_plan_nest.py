"""允许套餐使用 Panel 2.0 中没有分类的 Egg。"""

from alembic import op
import sqlalchemy as sa


revision = "20261102_optional_plan_nest"
down_revision = "20261022_payment_gateway"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("manager_billing_plans", "nest_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column("manager_billing_plans", "nest_id", existing_type=sa.Integer(), nullable=False)
