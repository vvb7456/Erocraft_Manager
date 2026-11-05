"""记录外部渠道退款编号。"""

from alembic import op
import sqlalchemy as sa


revision = "20261105_external_refund_id"
down_revision = "20261102_optional_plan_nest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("manager_billing_refunds", sa.Column("external_refund_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("manager_billing_refunds", "external_refund_id")
