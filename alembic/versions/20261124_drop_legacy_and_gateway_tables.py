"""清理 26 张已停用的历史废表（旧支付网关表、僵尸数据库管理表、原 Panel/Laravel 残表）。

revision ID 遵守 alembic_version.version_num VARCHAR(32) 上限约束（27 字符）。
"""

from __future__ import annotations

from alembic import op

revision = "20261124_drop_legacy_tables"
down_revision = "20261122_verify_code_attempts"
branch_labels = None
depends_on = None

# 严格按子表 -> 父表外键拓扑逆序删除，避免 MariaDB ON DELETE RESTRICT 拦截。
_TABLES_TO_DROP: tuple[str, ...] = (
    # 1. 9 张旧支付网关表（支付网关已迁至独立 payment_gateway 库）
    "gateway_deliveries",
    "gateway_notifications",
    "gateway_refunds",
    "gateway_wechat_sessions",
    "gateway_wechat_tokens",
    "gateway_jobs",
    "gateway_payments",
    "gateway_channel_accounts",
    "gateway_applications",
    # 2. 2 张僵尸数据库管理表（databases 引用 database_hosts）
    "databases",
    "database_hosts",
    # 3. 15 张纯 Laravel / 原 Panel 残表（tasks 引用 schedules）
    "tasks_log",
    "tasks",
    "schedules",
    "egg_mount",
    "api_keys",
    "api_logs",
    "audit_logs",
    "failed_jobs",
    "jobs",
    "migrations",
    "notifications",
    "password_resets",
    "recovery_tokens",
    "sessions",
    "settings",
)


def upgrade() -> None:
    for table_name in _TABLES_TO_DROP:
        op.execute(f"DROP TABLE IF EXISTS `{table_name}`")


def downgrade() -> None:
    # 被删废表数据请从发版前冷备恢复，版本回退不重建废空表且不影响旧版运行。
    pass
