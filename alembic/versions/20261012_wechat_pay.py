"""增加微信短期付款会话。"""

from alembic import op
import sqlalchemy as sa

revision = "20261012_wechat"
down_revision = "20261012_support"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manager_wechat_payment_sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("invoice_id", sa.BigInteger(), sa.ForeignKey("manager_billing_invoices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("scene", sa.String(16), nullable=False),
        sa.Column("appid", sa.String(32), nullable=False),
        sa.Column("openid", sa.String(128)),
        sa.Column("oauth_state_hash", sa.String(64)),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_manager_wechat_payment_sessions_invoice_id", "manager_wechat_payment_sessions", ["invoice_id"])
    op.create_index("ix_manager_wechat_payment_sessions_expires_at", "manager_wechat_payment_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_table("manager_wechat_payment_sessions")
