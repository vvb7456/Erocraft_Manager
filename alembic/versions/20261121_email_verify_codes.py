"""新增邮箱验证码表并清理过期的链接型自定义邮件模板覆盖。"""

from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import op

revision = "20261121_email_verify_codes"
down_revision = "20261111_redemption_codes"
branch_labels = None
depends_on = None

_LEGACY_LINK_VAR_RE = re.compile(r"\{\{\s*(verify_url|reset_url|confirm_url)\s*\}\}")
_USERNAME_VAR_RE = re.compile(r"\{\{\s*username\s*\}\}")
_LEGACY_LINK_COPY_RE = re.compile(
    r"(点击.{0,12}链接|此链接|验证链接|重置链接|确认链接|click.{0,20}link|verification link|reset link|confirmation link)",
    re.IGNORECASE,
)
_CODE_HINT_RE = re.compile(r"(验证码|verification_code|verification code)", re.IGNORECASE)


def _is_stale_link_template(template_key: str, subject: str, body: str) -> bool:
    combined = f"{subject}\n{body}"
    if _LEGACY_LINK_VAR_RE.search(combined):
        return True
    if template_key == "register_verify" and _USERNAME_VAR_RE.search(combined):
        return True
    if _LEGACY_LINK_COPY_RE.search(combined) and not _CODE_HINT_RE.search(combined):
        return True
    return False


def upgrade() -> None:
    op.create_table(
        "manager_email_verification_codes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=191), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_mevc_purpose_email_created",
        "manager_email_verification_codes",
        ["purpose", "email", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_mevc_user_purpose_created",
        "manager_email_verification_codes",
        ["user_id", "purpose", "created_at"],
        unique=False,
    )

    # 用 Python 检查并清理引用旧链接变量或旧链接文案的自定义模板，避开 MariaDB 与 MySQL 8 正则方言差异。
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT template_key, subject, body FROM manager_email_templates "
            "WHERE template_key IN ('register_verify', 'password_reset', 'email_change')"
        )
    ).fetchall()
    stale_keys = [
        row[0]
        for row in rows
        if _is_stale_link_template(str(row[0]), str(row[1] or ""), str(row[2] or ""))
    ]
    for key in stale_keys:
        bind.execute(
            sa.text("DELETE FROM manager_email_templates WHERE template_key = :key"),
            {"key": key},
        )

    # 旧链接式待验证注册表与邮箱变更表已彻底停用，升级时直接移除。
    op.execute(sa.text("DROP TABLE IF EXISTS manager_pending_registrations"))
    op.execute(sa.text("DROP TABLE IF EXISTS manager_email_changes"))


def downgrade() -> None:
    op.create_table(
        "manager_email_changes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("new_email", sa.String(length=255), nullable=False),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("current_timestamp()"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("idx_email_change_user_id", "manager_email_changes", ["user_id"], unique=False)

    op.create_table(
        "manager_pending_registrations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=191), nullable=False),
        sa.Column("first_name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("last_name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("lookup_hash", sa.String(length=64), nullable=False),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("inviter_user_id", sa.Integer(), nullable=True),
        sa.Column("invite_code", sa.String(length=8), nullable=True),
        sa.Column("agreements_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("current_timestamp()"), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("uq_pr_lookup_hash", "manager_pending_registrations", ["lookup_hash"], unique=True)
    op.create_index("idx_pr_email", "manager_pending_registrations", ["email"], unique=False)
    op.create_index("idx_pr_username", "manager_pending_registrations", ["username"], unique=False)
    op.create_index("idx_pr_inviter", "manager_pending_registrations", ["inviter_user_id"], unique=False)

    op.drop_index("ix_mevc_user_purpose_created", table_name="manager_email_verification_codes")
    op.drop_index("ix_mevc_purpose_email_created", table_name="manager_email_verification_codes")
    op.drop_table("manager_email_verification_codes")
