"""增加管理员通知投递队列及发送记录。"""

from alembic import op
import sqlalchemy as sa

revision = "20261014_notifications"
down_revision = "20261012_cancel_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manager_notification_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("dedup_key", sa.String(64), nullable=False),
        sa.Column("gateway_key", sa.String(64), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("topic", sa.String(120), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("recipient", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime()),
        sa.Column("sent_at", sa.DateTime()),
        sa.Column("last_error", sa.String(500)),
        sa.Column("message_id", sa.String(255)),
    )
    op.create_index("uq_notification_dedup", "manager_notification_deliveries", ["dedup_key"], unique=True)
    op.create_index("ix_notification_due", "manager_notification_deliveries", ["status", "available_at"])
    op.create_index("ix_notification_topic", "manager_notification_deliveries", ["topic", "created_at"])
    op.create_index("ix_notification_recipient", "manager_notification_deliveries", ["recipient", "last_attempt_at"])


def downgrade() -> None:
    op.drop_table("manager_notification_deliveries")
