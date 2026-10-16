"""增加小程序微信账号绑定与独立登录会话。"""

from alembic import op
import sqlalchemy as sa

revision = "20261016_miniprogram"
down_revision = "20261015_audit_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manager_miniprogram_bindings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("appid", sa.String(32), nullable=False),
        sa.Column("openid", sa.String(128, collation="utf8mb4_bin"), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("appid", "openid", name="uq_mini_wechat_identity"),
        sa.UniqueConstraint("appid", "user_id", name="uq_mini_user_identity"),
    )
    op.create_table(
        "manager_miniprogram_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("appid", sa.String(32), nullable=False),
        sa.Column("openid", sa.String(128, collation="utf8mb4_bin"), nullable=False),
        sa.Column("binding_id", sa.BigInteger(), sa.ForeignKey("manager_miniprogram_bindings.id", ondelete="CASCADE")),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_manager_miniprogram_sessions_binding_id", "manager_miniprogram_sessions", ["binding_id"])
    op.create_index("ix_manager_miniprogram_sessions_expires_at", "manager_miniprogram_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_table("manager_miniprogram_sessions")
    op.drop_table("manager_miniprogram_bindings")
