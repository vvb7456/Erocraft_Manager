"""增加站内客服会话及消息存储。"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import MEDIUMBLOB

revision = "20261012_support"
down_revision = "20260902_order_attr"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manager_support_conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("last_message_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("user_read_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("admin_read_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "manager_support_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.BigInteger(), sa.ForeignKey("manager_support_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_id", sa.Integer(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("image_type", sa.String(32)),
        sa.Column("image_data", MEDIUMBLOB()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("conversation_id", "sender_id", "client_id", name="uq_support_message_retry"),
    )
    op.create_index("ix_support_messages_conversation", "manager_support_messages", ["conversation_id", "id"])


def downgrade() -> None:
    op.drop_table("manager_support_messages")
    op.drop_table("manager_support_conversations")
