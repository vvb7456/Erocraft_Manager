"""rename monitoring tables to host-keyed names

Renames:
  manager_node_metrics  -> manager_host_metrics
  manager_node_alerts   -> manager_host_alerts
  manager_probe_results -> manager_host_probes

Also renames their indexes for consistency:
  idx_nm_*  -> idx_hm_*
  idx_na_*  -> idx_ha_*
  idx_pr_host_ts / idx_pr_ts / idx_pr_probe_ts -> idx_hp_*

Pure DDL rename: no data migration required (RENAME TABLE preserves rows).
"""

revision = "20260428_0007"
down_revision = "ea00339c95b9"
branch_labels = None
depends_on = None

from alembic import op


_TABLE_RENAMES = [
    ("manager_node_metrics", "manager_host_metrics"),
    ("manager_node_alerts", "manager_host_alerts"),
    ("manager_probe_results", "manager_host_probes"),
]


# (table_after_rename, old_index_name, new_index_name)
_INDEX_RENAMES_UP = [
    ("manager_host_metrics", "idx_nm_host_ts", "idx_hm_host_ts"),
    ("manager_host_metrics", "idx_nm_ts", "idx_hm_ts"),
    ("manager_host_alerts", "idx_na_host_active", "idx_ha_host_active"),
    ("manager_host_alerts", "idx_na_created", "idx_ha_created"),
    ("manager_host_probes", "idx_pr_host_ts", "idx_hp_host_ts"),
    ("manager_host_probes", "idx_pr_ts", "idx_hp_ts"),
    ("manager_host_probes", "idx_pr_probe_ts", "idx_hp_probe_ts"),
]


def upgrade() -> None:
    for old, new in _TABLE_RENAMES:
        op.rename_table(old, new)
    for table, old_idx, new_idx in _INDEX_RENAMES_UP:
        op.execute(f"ALTER TABLE {table} RENAME INDEX {old_idx} TO {new_idx}")


def downgrade() -> None:
    for table, old_idx, new_idx in _INDEX_RENAMES_UP:
        op.execute(f"ALTER TABLE {table} RENAME INDEX {new_idx} TO {old_idx}")
    for old, new in _TABLE_RENAMES:
        op.rename_table(new, old)
