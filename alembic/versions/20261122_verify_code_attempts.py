"""邮箱验证码表新增失败尝试计数字段，防止 6 位数字码被分布式爆破。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261122_verify_code_attempts"
down_revision = "20261121_email_verify_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "manager_email_verification_codes",
        sa.Column(
            "failed_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("manager_email_verification_codes", "failed_attempts")
