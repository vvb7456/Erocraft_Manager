"""接入统一支付网关，保留历史账目并分离小程序登录配置。"""

from alembic import op
import sqlalchemy as sa
import os

revision = "20261022_payment_gateway"
down_revision = "20261016_miniprogram"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("manager_billing_orders", "channel", existing_type=sa.String(32), existing_nullable=False, server_default="")
    op.execute(sa.text("""
        ALTER TABLE manager_billing_orders
          DROP INDEX uk_billing_orders_active_user,
          DROP COLUMN active_user_lock,
          ADD COLUMN active_user_lock INT GENERATED ALWAYS AS (
            CASE WHEN status = 'pending' THEN user_id END
          ) VIRTUAL,
          ADD UNIQUE KEY uk_billing_orders_active_user (active_user_lock)
    """))
    op.add_column("manager_billing_orders", sa.Column("close_reason", sa.String(16)))
    op.create_table(
        "manager_billing_payments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.BigInteger(), sa.ForeignKey("manager_billing_orders.id"), nullable=False),
        sa.Column("invoice_id", sa.BigInteger(), sa.ForeignKey("manager_billing_invoices.id"), nullable=False),
        sa.Column("request_id", sa.String(100), nullable=False, unique=True),
        sa.Column("request_body", sa.JSON(), nullable=False),
        sa.Column("gateway_id", sa.String(64), unique=True),
        sa.Column("checkout_url", sa.Text()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("method", sa.String(32)),
        sa.Column("close_requested", sa.Boolean(), nullable=False),
        sa.Column("channel_refunding", sa.Boolean(), nullable=False),
        sa.Column("transaction_id", sa.String(64)),
        sa.Column("paid_at", sa.DateTime()),
        sa.Column("delivery_confirmed_at", sa.DateTime()),
        sa.Column("last_error", sa.String(500)),
        sa.Column("synced_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_manager_billing_payments_order_id", "manager_billing_payments", ["order_id"])
    op.add_column("manager_billing_invoice_transactions", sa.Column("payment_id", sa.BigInteger(), sa.ForeignKey("manager_billing_payments.id")))
    op.create_unique_constraint("uq_billing_transaction_payment", "manager_billing_invoice_transactions", ["payment_id"])
    op.add_column("manager_billing_refunds", sa.Column("payment_id", sa.BigInteger(), sa.ForeignKey("manager_billing_payments.id")))
    op.create_index("ix_manager_billing_refunds_payment_id", "manager_billing_refunds", ["payment_id"])
    op.add_column("manager_billing_refunds", sa.Column("request_id", sa.String(100)))
    op.create_unique_constraint("uq_billing_refund_request", "manager_billing_refunds", ["request_id"])
    op.add_column("manager_billing_refunds", sa.Column("automatic", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("manager_billing_refunds", "transaction_id", existing_type=sa.BigInteger(), nullable=True)
    op.alter_column("manager_billing_refunds", "status", existing_type=sa.Enum("pending", "succeeded", "failed"), type_=sa.String(32), existing_nullable=False)
    # 旧退款恢复字段仅留作历史存档，新退款不再写入。
    op.alter_column("manager_billing_refunds", "previous_order_status", existing_type=sa.Enum("applied", "apply_failed", "manual_review"), type_=sa.String(32), nullable=True, server_default=None)
    op.add_column("manager_billing_payment_events", sa.Column("gateway_event_id", sa.String(64)))
    op.create_unique_constraint("uq_billing_gateway_event", "manager_billing_payment_events", ["gateway_event_id"])
    # 加密值不依赖配置键名，直接复制可保持原登录身份与会话有效。
    for new_key, old_key in (
        ("MINIPROGRAM_APPID", "WECHAT_PAY_MINIPROGRAM_APPID"),
        ("MINIPROGRAM_APP_SECRET", "WECHAT_PAY_MINIPROGRAM_APP_SECRET"),
        ("LEGACY_ALIPAY_APPID", "ALIPAY_DIRECT_APPID"),
        ("LEGACY_ALIPAY_PUBLIC_KEY", "ALIPAY_DIRECT_ALIPAY_PUBLIC_KEY"),
    ):
        op.execute(sa.text("""
            INSERT INTO manager_system_settings (`key`, category, value_type, value_text, value_encrypted, version)
            SELECT :new_key, category, value_type, value_text, value_encrypted, version
            FROM manager_system_settings WHERE `key` = :old_key
        """).bindparams(new_key=new_key, old_key=old_key))
        if os.getenv(old_key) and not op.get_bind().scalar(sa.text("SELECT 1 FROM manager_system_settings WHERE `key`=:key"), {"key": new_key}):
            from app.core.config import get_settings
            from app.core.security import encrypt_value
            op.execute(sa.text("""
                INSERT INTO manager_system_settings (`key`, category, value_type, value_encrypted, version)
                VALUES (:key, 'billing', 'string', :value, 1)
            """).bindparams(key=new_key, value=encrypt_value(os.environ[old_key], get_settings().settings_encryption_key)))
    op.drop_table("manager_wechat_payment_sessions")


def downgrade() -> None:
    raise RuntimeError("本迁移包含支付及退款记录，请从备份恢复，不能删除财务数据回退。")
