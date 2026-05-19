"""Clean baseline for all manager_* tables.

Replaces every previous migration (squashed 0001–0012 baseline +
``server_install_notify``). This single revision creates each
``manager_*`` table in its current, final shape. Project hasn't shipped
yet, so we squash freely; existing dev databases are migrated via a
manual ``ALTER TABLE manager_hosts DROP COLUMN inbound_reachable,
DROP COLUMN last_status_at;`` plus ``UPDATE alembic_version SET
version_num='20260507_baseline'``.
"""

from __future__ import annotations

from alembic import op


revision = "20260507_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE `manager_hosts` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL,
  `kind` varchar(32) NOT NULL,
  `hostname` varchar(255) NOT NULL,
  `agent_url` varchar(255) NOT NULL,
  `agent_token_enc` text NOT NULL,
  `pterodactyl_node_id` int(10) unsigned DEFAULT NULL,
  `extra_metadata` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`extra_metadata`)),
  `enabled` tinyint(1) NOT NULL DEFAULT 1,
  `last_seen_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_pterodactyl_node` (`pterodactyl_node_id`),
  KEY `idx_kind` (`kind`),
  KEY `idx_enabled` (`enabled`),
  CONSTRAINT `manager_hosts_ibfk_1` FOREIGN KEY (`pterodactyl_node_id`) REFERENCES `nodes` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_certificates` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL,
  `domains` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`domains`)),
  `source_type` varchar(32) NOT NULL,
  `source_path` varchar(512) NOT NULL,
  `source_fingerprint_sha256` varchar(64) DEFAULT NULL,
  `source_not_before` datetime DEFAULT NULL,
  `source_not_after` datetime DEFAULT NULL,
  `source_last_seen_at` datetime DEFAULT NULL,
  `source_last_error` text DEFAULT NULL,
  `alert_threshold_days` int(11) NOT NULL DEFAULT 14,
  `enabled` tinyint(1) NOT NULL DEFAULT 1,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_manager_cert_enabled` (`enabled`),
  KEY `idx_manager_cert_source_path` (`source_path`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_cert_deployments` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `certificate_id` int(11) NOT NULL,
  `host_id` int(11) NOT NULL,
  `target_name` varchar(64) NOT NULL DEFAULT '',
  `deployed_fingerprint_sha256` varchar(64) DEFAULT NULL,
  `deployed_not_after` datetime DEFAULT NULL,
  `last_check_at` datetime DEFAULT NULL,
  `last_check_error` text DEFAULT NULL,
  `last_deploy_at` datetime DEFAULT NULL,
  `last_deploy_attempt_at` datetime DEFAULT NULL,
  `last_deploy_error` text DEFAULT NULL,
  `status` varchar(32) NOT NULL DEFAULT 'unknown',
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_manager_cert_deployment_target` (`certificate_id`,`host_id`,`target_name`),
  KEY `idx_manager_cert_deploy_cert` (`certificate_id`),
  KEY `idx_manager_cert_deploy_host` (`host_id`),
  KEY `idx_manager_cert_deploy_status` (`status`),
  CONSTRAINT `manager_cert_deployments_ibfk_1` FOREIGN KEY (`certificate_id`) REFERENCES `manager_certificates` (`id`) ON DELETE CASCADE,
  CONSTRAINT `manager_cert_deployments_ibfk_2` FOREIGN KEY (`host_id`) REFERENCES `manager_hosts` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_host_alerts` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `alert_type` varchar(30) NOT NULL,
  `severity` varchar(10) NOT NULL DEFAULT 'warning',
  `message` varchar(500) DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `resolved_at` datetime DEFAULT NULL,
  `notified` tinyint(1) NOT NULL DEFAULT 0,
  `last_notified_at` datetime DEFAULT NULL,
  `host_id` bigint(20) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_ha_host_active` (`host_id`,`resolved_at`),
  KEY `idx_ha_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_host_alert_rules` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `host_id` int(11) NOT NULL,
  `alert_type` varchar(50) NOT NULL,
  `enabled` tinyint(1) NOT NULL DEFAULT 1,
  `threshold` float DEFAULT NULL,
  `warning_threshold` float DEFAULT NULL,
  `critical_threshold` float DEFAULT NULL,
  `sustain_min` int(11) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_host_type` (`host_id`,`alert_type`),
  KEY `idx_host_alert_host` (`host_id`),
  CONSTRAINT `manager_host_alert_rules_ibfk_1` FOREIGN KEY (`host_id`) REFERENCES `manager_hosts` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_host_alert_settings` (
  `host_id` int(11) NOT NULL,
  `email_enabled` tinyint(1) DEFAULT NULL,
  `email_recipients` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`email_recipients`)),
  `min_severity` varchar(20) DEFAULT NULL,
  `notify_resolve` tinyint(1) DEFAULT NULL,
  `cooldown_min` int(11) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`host_id`),
  CONSTRAINT `manager_host_alert_settings_ibfk_1` FOREIGN KEY (`host_id`) REFERENCES `manager_hosts` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_host_metrics` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `ts` datetime NOT NULL,
  `agent_online` tinyint(1) NOT NULL DEFAULT 0,
  `wings_online` tinyint(1) NOT NULL DEFAULT 0,
  `public_reachable` tinyint(1) DEFAULT NULL,
  `cpu_pct` float DEFAULT NULL,
  `cpu_cores` smallint(6) DEFAULT NULL,
  `load_1m` float DEFAULT NULL,
  `load_5m` float DEFAULT NULL,
  `load_15m` float DEFAULT NULL,
  `mem_total_mb` int(11) DEFAULT NULL,
  `mem_used_mb` int(11) DEFAULT NULL,
  `mem_pct` float DEFAULT NULL,
  `disk_total_mb` int(11) DEFAULT NULL,
  `disk_used_mb` int(11) DEFAULT NULL,
  `disk_pct` float DEFAULT NULL,
  `net_rx_bps` bigint(20) DEFAULT NULL,
  `net_tx_bps` bigint(20) DEFAULT NULL,
  `wings_version` varchar(20) DEFAULT NULL,
  `container_total` smallint(6) DEFAULT NULL,
  `container_running` smallint(6) DEFAULT NULL,
  `container_mem_mb` int(11) DEFAULT NULL,
  `container_cpu_pct` float DEFAULT NULL,
  `container_disk_mb` int(11) DEFAULT NULL,
  `swap_total_mb` int(11) DEFAULT NULL,
  `swap_used_mb` int(11) DEFAULT NULL,
  `uptime_sec` bigint(20) DEFAULT NULL,
  `disk_read_bps` bigint(20) DEFAULT NULL,
  `disk_write_bps` bigint(20) DEFAULT NULL,
  `host_id` bigint(20) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_hm_host_ts` (`host_id`,`ts`),
  KEY `idx_hm_ts` (`ts`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_host_probes` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `ts` datetime NOT NULL,
  `source` varchar(20) NOT NULL,
  `probe_name` varchar(50) NOT NULL,
  `ok` tinyint(1) NOT NULL,
  `latency_ms` float DEFAULT NULL,
  `error_msg` varchar(200) DEFAULT NULL,
  `host_id` bigint(20) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_hp_ts` (`ts`),
  KEY `idx_hp_probe_ts` (`probe_name`,`ts`),
  KEY `idx_hp_host_ts` (`host_id`,`ts`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_host_tunnels` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `host_id` int(11) NOT NULL,
  `cf_account_id` varchar(64) NOT NULL,
  `cf_api_token_enc` text NOT NULL,
  `cf_zone_id` varchar(64) NOT NULL,
  `cf_zone_name` varchar(255) NOT NULL,
  `cf_tunnel_id` varchar(64) DEFAULT NULL,
  `cf_tunnel_name` varchar(255) DEFAULT NULL,
  `cf_tunnel_secret_enc` text DEFAULT NULL,
  `cloudflared_version` varchar(32) DEFAULT NULL,
  `cf_config_version` int(11) DEFAULT NULL,
  `last_synced_at` datetime DEFAULT NULL,
  `last_error` text DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_host_tunnel_host` (`host_id`),
  CONSTRAINT `manager_host_tunnels_ibfk_1` FOREIGN KEY (`host_id`) REFERENCES `manager_hosts` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_server_tunnels` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `server_id` int(11) NOT NULL,
  `host_tunnel_id` int(11) NOT NULL,
  `hostname` varchar(255) NOT NULL,
  `custom_subdomain` varchar(64) DEFAULT NULL,
  `upstream_port` int(11) NOT NULL,
  `upstream_scheme` varchar(8) NOT NULL DEFAULT 'http',
  `cf_dns_record_id` varchar(64) DEFAULT NULL,
  `status` varchar(20) NOT NULL DEFAULT 'provisioning',
  `last_error` text DEFAULT NULL,
  `enabled_at` datetime DEFAULT NULL,
  `last_synced_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_server_tunnel_server` (`server_id`),
  UNIQUE KEY `uk_server_tunnel_hostname` (`hostname`),
  KEY `ix_server_tunnel_status` (`status`),
  KEY `ix_server_tunnel_host_tunnel` (`host_tunnel_id`),
  CONSTRAINT `manager_server_tunnels_ibfk_1` FOREIGN KEY (`host_tunnel_id`) REFERENCES `manager_host_tunnels` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_orphan_resources` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `resource_type` varchar(32) NOT NULL,
  `cf_account_id` varchar(64) NOT NULL,
  `cf_zone_id` varchar(64) DEFAULT NULL,
  `cf_resource_id` varchar(64) NOT NULL,
  `cf_resource_name` varchar(255) NOT NULL,
  `detected_at` datetime NOT NULL DEFAULT current_timestamp(),
  `notes` text DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_orphan_resource` (`resource_type`,`cf_resource_id`),
  KEY `ix_orphan_type` (`resource_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_server_meta` (
  `server_id` int(10) unsigned NOT NULL,
  `expiration_date` date DEFAULT NULL,
  `plan_id` bigint(20) DEFAULT NULL,
  `install_notified_at` datetime DEFAULT NULL,
  PRIMARY KEY (`server_id`),
  KEY `idx_server_meta_plan` (`plan_id`),
  CONSTRAINT `manager_server_meta_ibfk_1` FOREIGN KEY (`server_id`) REFERENCES `servers` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_activity_logs` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `timestamp` timestamp NOT NULL DEFAULT current_timestamp(),
  `actor` varchar(100) NOT NULL,
  `category` varchar(32) NOT NULL DEFAULT 'other',
  `status` varchar(50) NOT NULL,
  `detail_key` varchar(120) DEFAULT NULL,
  `detail_params` text DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_timestamp` (`timestamp`),
  KEY `idx_actor` (`actor`),
  KEY `idx_category` (`category`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_email_changes` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `new_email` varchar(255) NOT NULL,
  `token` varchar(255) NOT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `confirmed_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_email_change_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_email_templates` (
  `template_key` varchar(64) NOT NULL,
  `subject` text NOT NULL,
  `body` text NOT NULL,
  `updated_at` datetime DEFAULT current_timestamp(),
  PRIMARY KEY (`template_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_password_resets` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `token` varchar(255) NOT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `used_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_pw_reset_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_pending_registrations` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `email` varchar(255) NOT NULL,
  `username` varchar(191) NOT NULL,
  `first_name` varchar(255) NOT NULL DEFAULT '',
  `last_name` varchar(255) NOT NULL DEFAULT '',
  `password_hash` varchar(255) NOT NULL,
  `token` varchar(255) NOT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `used_at` datetime DEFAULT NULL,
  `lookup_hash` varchar(64) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_pr_lookup_hash` (`lookup_hash`),
  KEY `idx_pr_email` (`email`),
  KEY `idx_pr_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_system_settings` (
  `key` varchar(64) NOT NULL,
  `category` varchar(32) NOT NULL,
  `value_text` text DEFAULT NULL,
  `value_encrypted` text DEFAULT NULL,
  `value_type` varchar(16) NOT NULL DEFAULT 'string',
  `version` bigint(20) NOT NULL DEFAULT 1,
  `updated_at` datetime DEFAULT current_timestamp(),
  PRIMARY KEY (`key`),
  KEY `idx_category` (`category`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_billing_plans` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `code` varchar(64) NOT NULL,
  `display_name` varchar(128) NOT NULL,
  `price_fen` int(11) NOT NULL,
  `days` int(11) NOT NULL,
  `currency_code` char(3) NOT NULL DEFAULT 'CNY',
  `period_options` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`period_options`)),
  `node_id` int(11) NOT NULL,
  `egg_id` int(11) NOT NULL,
  `nest_id` int(11) NOT NULL,
  `cpu` int(11) NOT NULL,
  `memory_mb` int(11) NOT NULL,
  `disk_mb` int(11) NOT NULL,
  `swap_mb` int(11) NOT NULL DEFAULT 0,
  `io` int(11) NOT NULL DEFAULT 500,
  `database_limit` int(11) NOT NULL DEFAULT 0,
  `backup_limit` int(11) NOT NULL DEFAULT 0,
  `allocation_limit` int(11) NOT NULL,
  `oom_disabled` tinyint(1) NOT NULL DEFAULT 1,
  `docker_image` varchar(255) NOT NULL,
  `startup_command` text NOT NULL,
  `env_defaults` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`env_defaults`)),
  `is_active` tinyint(1) NOT NULL DEFAULT 1,
  `display_order` int(11) NOT NULL DEFAULT 0,
  `description_md` text DEFAULT NULL,
  `category_label` varchar(64) DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_billing_plans_code` (`code`),
  KEY `idx_billing_plans_active` (`is_active`),
  CONSTRAINT `chk_billing_plans_days_pos` CHECK (`days` > 0),
  CONSTRAINT `chk_billing_plans_price_pos` CHECK (`price_fen` > 0),
  CONSTRAINT `chk_billing_plans_cpu_pos` CHECK (`cpu` > 0),
  CONSTRAINT `chk_billing_plans_memory_pos` CHECK (`memory_mb` > 0),
  CONSTRAINT `chk_billing_plans_disk_pos` CHECK (`disk_mb` > 0),
  CONSTRAINT `chk_billing_plans_alloc_pos` CHECK (`allocation_limit` > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_billing_orders` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `order_no` varchar(32) NOT NULL,
  `user_id` int(11) NOT NULL,
  `plan_id` bigint(20) DEFAULT NULL,
  `plan_snapshot` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`plan_snapshot`)),
  `kind` enum('renew','new_purchase','upgrade') NOT NULL,
  `period_count` int(11) NOT NULL DEFAULT 1,
  `discount_pct` decimal(5,2) NOT NULL DEFAULT 0.00,
  `total_fen` int(11) NOT NULL,
  `total_days` int(11) NOT NULL,
  `target_server_id` int(11) DEFAULT NULL,
  `reserved_node_id` int(11) DEFAULT NULL,
  `reserved_allocation_id` int(11) DEFAULT NULL,
  `reserved_additional_allocations` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`reserved_additional_allocations`)),
  `status` enum('pending','processing','applied','apply_failed','closed','cancelled','refunding','refunded','manual_review') NOT NULL DEFAULT 'pending',
  `received_fen` int(11) NOT NULL DEFAULT 0,
  `refunded_fen` int(11) NOT NULL DEFAULT 0,
  `apply_retry_count` int(11) NOT NULL DEFAULT 0,
  `next_apply_at` datetime DEFAULT NULL,
  `last_apply_error` varchar(500) DEFAULT NULL,
  `lock_token` char(36) DEFAULT NULL,
  `locked_until` datetime DEFAULT NULL,
  `applied_at` datetime DEFAULT NULL,
  `closed_at` datetime DEFAULT NULL,
  `cancelled_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  `active_user_lock` int(11) GENERATED ALWAYS AS (CASE WHEN `status` IN ('pending','processing','manual_review') THEN `user_id` END) VIRTUAL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_billing_orders_order_no` (`order_no`),
  UNIQUE KEY `uk_billing_orders_active_user` (`active_user_lock`),
  KEY `fk_billing_orders_plan` (`plan_id`),
  KEY `idx_billing_orders_user_status` (`user_id`,`status`,`created_at`),
  KEY `idx_billing_orders_status_next_apply` (`status`,`next_apply_at`),
  KEY `idx_billing_orders_locked` (`locked_until`),
  CONSTRAINT `fk_billing_orders_plan` FOREIGN KEY (`plan_id`) REFERENCES `manager_billing_plans` (`id`) ON DELETE SET NULL,
  CONSTRAINT `chk_billing_orders_renew_target` CHECK (`kind` <> 'renew' or `target_server_id` is not null),
  CONSTRAINT `chk_billing_orders_received_nonneg` CHECK (`received_fen` >= 0 and `refunded_fen` >= 0),
  CONSTRAINT `chk_billing_orders_refunded_le_received` CHECK (`refunded_fen` <= `received_fen`),
  CONSTRAINT `chk_billing_orders_period_count_pos` CHECK (`period_count` > 0),
  CONSTRAINT `chk_billing_orders_total_fen_pos` CHECK (`total_fen` > 0),
  CONSTRAINT `chk_billing_orders_total_days_pos` CHECK (`total_days` >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_billing_invoices` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `invoice_no` varchar(32) NOT NULL,
  `order_id` bigint(20) NOT NULL,
  `user_id` int(11) NOT NULL,
  `status` enum('pending','paid','void') NOT NULL DEFAULT 'pending',
  `total_fen` int(11) NOT NULL,
  `currency_code` char(3) NOT NULL DEFAULT 'CNY',
  `due_at` datetime DEFAULT NULL,
  `paid_at` datetime DEFAULT NULL,
  `gateway_code` varchar(32) DEFAULT NULL,
  `gateway_prepay_id` varchar(64) DEFAULT NULL,
  `gateway_code_url` varchar(512) DEFAULT NULL,
  `gateway_payload` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`gateway_payload`)),
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_billing_invoices_invoice_no` (`invoice_no`),
  KEY `idx_billing_invoices_order` (`order_id`),
  KEY `idx_billing_invoices_user_status` (`user_id`,`status`,`created_at`),
  KEY `idx_billing_invoices_status_due` (`status`,`due_at`),
  CONSTRAINT `fk_billing_invoices_order` FOREIGN KEY (`order_id`) REFERENCES `manager_billing_orders` (`id`) ON DELETE CASCADE,
  CONSTRAINT `chk_billing_invoices_total_pos` CHECK (`total_fen` > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_billing_invoice_items` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `invoice_id` bigint(20) NOT NULL,
  `ref_type` varchar(32) NOT NULL,
  `ref_id` bigint(20) NOT NULL,
  `description` varchar(255) NOT NULL,
  `price_fen` int(11) NOT NULL,
  `quantity` int(11) NOT NULL DEFAULT 1,
  `meta` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`meta`)),
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_billing_invoice_items_ref` (`invoice_id`,`ref_type`,`ref_id`),
  KEY `idx_billing_invoice_items_invoice` (`invoice_id`),
  KEY `idx_billing_invoice_items_ref` (`ref_type`,`ref_id`),
  CONSTRAINT `fk_billing_invoice_items_invoice` FOREIGN KEY (`invoice_id`) REFERENCES `manager_billing_invoices` (`id`) ON DELETE CASCADE,
  CONSTRAINT `chk_billing_invoice_items_qty_pos` CHECK (`quantity` > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_billing_invoice_transactions` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `invoice_id` bigint(20) NOT NULL,
  `gateway_code` varchar(32) NOT NULL,
  `transaction_id` varchar(64) NOT NULL,
  `amount_fen` int(11) NOT NULL,
  `fee_fen` int(11) DEFAULT NULL,
  `status` enum('succeeded','failed','refunded') NOT NULL,
  `refunded_fen` int(11) NOT NULL DEFAULT 0,
  `raw_event_id` bigint(20) DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_billing_invoice_tx_gateway` (`gateway_code`,`transaction_id`),
  KEY `idx_billing_invoice_tx_invoice_status` (`invoice_id`,`status`),
  CONSTRAINT `fk_billing_invoice_tx_invoice` FOREIGN KEY (`invoice_id`) REFERENCES `manager_billing_invoices` (`id`) ON DELETE CASCADE,
  CONSTRAINT `chk_billing_invoice_tx_amount_pos` CHECK (`amount_fen` > 0),
  CONSTRAINT `chk_billing_invoice_tx_refunded` CHECK (`refunded_fen` >= 0 and `refunded_fen` <= `amount_fen`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_billing_refunds` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `refund_no` varchar(32) NOT NULL,
  `transaction_id` bigint(20) NOT NULL,
  `order_id` bigint(20) NOT NULL,
  `amount_fen` int(11) NOT NULL,
  `status` enum('pending','succeeded','failed') NOT NULL DEFAULT 'pending',
  `reason` varchar(255) DEFAULT NULL,
  `previous_order_status` enum('applied','apply_failed','manual_review') NOT NULL DEFAULT 'applied',
  `gateway_refund_id` varchar(64) DEFAULT NULL,
  `retry_count` int(11) NOT NULL DEFAULT 0,
  `last_error` varchar(500) DEFAULT NULL,
  `initiated_by` int(11) DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_billing_refunds_refund_no` (`refund_no`),
  KEY `idx_billing_refunds_tx` (`transaction_id`),
  KEY `idx_billing_refunds_order` (`order_id`),
  KEY `idx_billing_refunds_status` (`status`),
  CONSTRAINT `fk_billing_refunds_order` FOREIGN KEY (`order_id`) REFERENCES `manager_billing_orders` (`id`),
  CONSTRAINT `fk_billing_refunds_tx` FOREIGN KEY (`transaction_id`) REFERENCES `manager_billing_invoice_transactions` (`id`),
  CONSTRAINT `chk_billing_refunds_amount_pos` CHECK (`amount_fen` > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_billing_order_effects` (
  `order_id` bigint(20) NOT NULL,
  `effect_type` enum('renew','new_purchase','upgrade') NOT NULL,
  `server_id` int(11) NOT NULL,
  `days` int(11) NOT NULL,
  `prev_expiration_date` date DEFAULT NULL,
  `new_expiration_date` date NOT NULL,
  `effect_committed_at` datetime NOT NULL,
  `post_actions_done_at` datetime DEFAULT NULL,
  PRIMARY KEY (`order_id`),
  KEY `idx_billing_order_effects_server` (`server_id`),
  CONSTRAINT `fk_billing_order_effects_order` FOREIGN KEY (`order_id`) REFERENCES `manager_billing_orders` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_billing_payment_events` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `gateway_code` varchar(32) NOT NULL,
  `event_type` varchar(64) NOT NULL,
  `signature_ok` tinyint(1) NOT NULL,
  `invoice_id` bigint(20) DEFAULT NULL,
  `transaction_id` varchar(64) DEFAULT NULL,
  `raw_headers` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`raw_headers`)),
  `raw_body` longtext NOT NULL,
  `received_at` datetime NOT NULL,
  `processed_at` datetime DEFAULT NULL,
  `process_result` varchar(64) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_billing_payment_events_invoice` (`invoice_id`),
  KEY `idx_billing_payment_events_gateway_tx` (`gateway_code`,`transaction_id`),
  KEY `idx_billing_payment_events_received` (`received_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_billing_incidents` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `kind` enum('manual_review_required','apply_retries_exhausted','refund_retries_exhausted','placeholder_leak','placeholder_cleanup_failed') NOT NULL,
  `order_id` bigint(20) DEFAULT NULL,
  `invoice_id` bigint(20) DEFAULT NULL,
  `transaction_id` bigint(20) DEFAULT NULL,
  `server_id` int(11) DEFAULT NULL,
  `payload` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`payload`)),
  `detected_at` datetime NOT NULL,
  `status` enum('open','investigating','resolved','wontfix') NOT NULL DEFAULT 'open',
  `resolution_note` text DEFAULT NULL,
  `resolved_by` int(11) DEFAULT NULL,
  `resolved_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_billing_incidents_status_kind` (`status`,`kind`),
  KEY `idx_billing_incidents_order` (`order_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS `manager_billing_incidents`")
    op.execute("DROP TABLE IF EXISTS `manager_billing_payment_events`")
    op.execute("DROP TABLE IF EXISTS `manager_billing_order_effects`")
    op.execute("DROP TABLE IF EXISTS `manager_billing_refunds`")
    op.execute("DROP TABLE IF EXISTS `manager_billing_invoice_transactions`")
    op.execute("DROP TABLE IF EXISTS `manager_billing_invoice_items`")
    op.execute("DROP TABLE IF EXISTS `manager_billing_invoices`")
    op.execute("DROP TABLE IF EXISTS `manager_billing_orders`")
    op.execute("DROP TABLE IF EXISTS `manager_billing_plans`")
    op.execute("DROP TABLE IF EXISTS `manager_system_settings`")
    op.execute("DROP TABLE IF EXISTS `manager_pending_registrations`")
    op.execute("DROP TABLE IF EXISTS `manager_password_resets`")
    op.execute("DROP TABLE IF EXISTS `manager_email_templates`")
    op.execute("DROP TABLE IF EXISTS `manager_email_changes`")
    op.execute("DROP TABLE IF EXISTS `manager_activity_logs`")
    op.execute("DROP TABLE IF EXISTS `manager_server_meta`")
    op.execute("DROP TABLE IF EXISTS `manager_orphan_resources`")
    op.execute("DROP TABLE IF EXISTS `manager_server_tunnels`")
    op.execute("DROP TABLE IF EXISTS `manager_host_tunnels`")
    op.execute("DROP TABLE IF EXISTS `manager_host_probes`")
    op.execute("DROP TABLE IF EXISTS `manager_host_metrics`")
    op.execute("DROP TABLE IF EXISTS `manager_host_alert_settings`")
    op.execute("DROP TABLE IF EXISTS `manager_host_alert_rules`")
    op.execute("DROP TABLE IF EXISTS `manager_host_alerts`")
    op.execute("DROP TABLE IF EXISTS `manager_cert_deployments`")
    op.execute("DROP TABLE IF EXISTS `manager_certificates`")
    op.execute("DROP TABLE IF EXISTS `manager_hosts`")
