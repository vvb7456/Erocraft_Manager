"""统一通知渠道及告警处理状态。"""

from alembic import op
import sqlalchemy as sa

revision = "20261014_notification_center"
down_revision = "20261014_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("manager_notification_issues",
        sa.Column("key", sa.String(190), primary_key=True),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime()),
        sa.Column("muted_until", sa.DateTime()),
        sa.Column("resolved_at", sa.DateTime()))
    op.add_column("manager_notification_deliveries", sa.Column("channel", sa.String(16), nullable=False, server_default="wecom"))
    op.alter_column("manager_notification_deliveries", "recipient", existing_type=sa.String(64), type_=sa.String(255), existing_nullable=False)
    op.add_column("manager_host_alerts", sa.Column("acknowledged_at", sa.DateTime()))
    op.add_column("manager_host_alerts", sa.Column("muted_until", sa.DateTime()))
    op.alter_column("manager_host_alert_rules", "enabled", existing_type=sa.Boolean(), nullable=True)
    op.add_column("manager_cert_deployments", sa.Column("unhealthy_since", sa.DateTime()))
    op.execute("UPDATE manager_cert_deployments SET unhealthy_since = COALESCE(last_check_at, created_at) WHERE status <> 'synced'")


def downgrade() -> None:
    op.drop_table("manager_notification_issues")
    op.drop_column("manager_cert_deployments", "unhealthy_since")
    op.execute("UPDATE manager_host_alert_rules SET enabled = 1 WHERE enabled IS NULL")
    op.alter_column("manager_host_alert_rules", "enabled", existing_type=sa.Boolean(), nullable=False)
    op.drop_column("manager_host_alerts", "muted_until")
    op.drop_column("manager_host_alerts", "acknowledged_at")
    op.drop_column("manager_notification_deliveries", "channel")
