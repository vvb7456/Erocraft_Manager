"""阶段 5A+5B 数据模型收口：端口预留锁、实例生命周期属性归位与三张废表退役。

变更摘要：
1. ``allocations`` 新增 ``reserved_order_id``（带外键与索引）、``reserved_until`` 及可用性联合索引；
2. ``servers`` 新增 ``expiration_date``、``plan_id``（无外键，建索引）、``is_trial``、
   ``install_notified_at`` 及到期/试用联合索引；
3. 单条 SQL 将 ``manager_server_meta`` 全量有效生命周期数据迁移至 ``servers``；
4. 清理已退役的 ``manager_server_meta``、``subusers``、``user_ssh_keys`` 三张表
   （保留 ``mounts``/``mount_node``/``mount_server``/``backups``/``server_transfers``）。

revision ID 遵守 alembic_version.version_num VARCHAR(32) 上限约束（30 字符）。
"""

from __future__ import annotations

from alembic import op

revision = "20261126_phase5ab_domain_align"
down_revision = "20261124_drop_legacy_tables"
branch_labels = None
depends_on = None

_TABLES_TO_DROP: tuple[str, ...] = (
    "manager_server_meta",
    "subusers",
    "user_ssh_keys",
)


def upgrade() -> None:
    # 1. allocations: 新增端口预留锁字段、索引与外键（signed BIGINT 精确匹配 manager_billing_orders.id）
    op.execute(
        """
ALTER TABLE `allocations`
  ADD COLUMN `reserved_order_id` bigint(20) DEFAULT NULL AFTER `notes`,
  ADD COLUMN `reserved_until` datetime DEFAULT NULL AFTER `reserved_order_id`,
  ADD KEY `idx_allocations_reserved_order` (`reserved_order_id`),
  ADD KEY `idx_allocations_node_avail` (`node_id`, `server_id`, `reserved_until`),
  ADD CONSTRAINT `allocations_reserved_order_id_foreign`
    FOREIGN KEY (`reserved_order_id`) REFERENCES `manager_billing_orders` (`id`)
    ON DELETE SET NULL
        """
    )

    # 2. servers: 新增实例一等生命周期属性与索引（plan_id 不建 FK，允许删除套餐后保留订单快照绑定）
    op.execute(
        """
ALTER TABLE `servers`
  ADD COLUMN `expiration_date` date DEFAULT NULL AFTER `installed_at`,
  ADD COLUMN `plan_id` bigint(20) DEFAULT NULL AFTER `expiration_date`,
  ADD COLUMN `is_trial` tinyint(1) NOT NULL DEFAULT 0 AFTER `plan_id`,
  ADD COLUMN `install_notified_at` datetime DEFAULT NULL AFTER `is_trial`,
  ADD KEY `idx_servers_plan_id` (`plan_id`),
  ADD KEY `idx_servers_expiration_trial` (`expiration_date`, `is_trial`)
        """
    )

    # 3. 将 manager_server_meta 存量生命周期字段全量拷贝至 servers（空库与实库均幂等安全）
    op.execute(
        """
UPDATE `servers` s
INNER JOIN `manager_server_meta` m ON m.`server_id` = s.`id`
SET
  s.`expiration_date` = m.`expiration_date`,
  s.`plan_id` = m.`plan_id`,
  s.`is_trial` = m.`is_trial`,
  s.`install_notified_at` = m.`install_notified_at`
        """
    )

    # 4. 清理已退役表
    for table_name in _TABLES_TO_DROP:
        op.execute(f"DROP TABLE IF EXISTS `{table_name}`")


def downgrade() -> None:
    # 本次迁移包含数据归并及历史废表退役，版本回退不执行破坏性反向 DDL；
    # 如需回滚数据库结构与历史表数据，请使用发版前冷备恢复。
    pass
