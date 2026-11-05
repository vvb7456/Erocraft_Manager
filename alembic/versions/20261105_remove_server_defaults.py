"""清理已停用的服务器默认配置。"""

from alembic import op
import sqlalchemy as sa


revision = "20261105_remove_server_defaults"
down_revision = "20261105_external_refund_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    settings = sa.table("manager_system_settings", sa.column("key", sa.String))
    op.execute(settings.delete().where(settings.c.key.in_([
        "DEFAULT_ALLOCATIONS",
        "DEFAULT_BACKUPS",
        "DEFAULT_CPU",
        "DEFAULT_DATABASES",
        "DEFAULT_DISK",
        "DEFAULT_EGG_ID",
        "DEFAULT_MEMORY",
        "DEFAULT_NEST_ID",
        "DEFAULT_NODE_ID",
        "DOCKER_IMAGE",
    ])))


def downgrade() -> None:
    pass
