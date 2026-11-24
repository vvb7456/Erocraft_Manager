"""Baseline for the 18 active unprefixed core tables (formerly managed by Panel).

Creates all 18 active unprefixed core tables in foreign-key topological order
with idempotent ``CREATE TABLE IF NOT EXISTS`` statements matching production
MariaDB 11.8 (``utf8mb4_unicode_ci``).

Notes:
- ``users`` intentionally omits ``has_owned_server`` so that the existing
  ``20260619_trial`` migration adds it cleanly on fresh databases.
- ``allocations.server_id`` foreign key is added after ``servers`` is created
  (only when absent) to break the ``allocations <-> servers`` FK cycle.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

revision = "20260506_ptero_core_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `users` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `external_id` varchar(191) DEFAULT NULL,
  `uuid` char(36) NOT NULL,
  `username` varchar(191) NOT NULL,
  `email` varchar(191) NOT NULL,
  `name_first` varchar(191) DEFAULT NULL,
  `name_last` varchar(191) DEFAULT NULL,
  `password` text NOT NULL,
  `remember_token` varchar(191) DEFAULT NULL,
  `language` char(5) NOT NULL DEFAULT 'en',
  `root_admin` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `use_totp` tinyint(3) unsigned NOT NULL,
  `totp_secret` text DEFAULT NULL,
  `totp_authenticated_at` timestamp NULL DEFAULT NULL,
  `gravatar` tinyint(1) NOT NULL DEFAULT 1,
  `created_at` timestamp NULL DEFAULT NULL,
  `updated_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `users_uuid_unique` (`uuid`),
  UNIQUE KEY `users_email_unique` (`email`),
  UNIQUE KEY `users_username_unique` (`username`),
  KEY `users_external_id_index` (`external_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `locations` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `short` varchar(191) NOT NULL,
  `long` text DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT NULL,
  `updated_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `locations_short_unique` (`short`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `nodes` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `uuid` char(36) NOT NULL,
  `public` smallint(5) unsigned NOT NULL,
  `name` varchar(191) NOT NULL,
  `description` text DEFAULT NULL,
  `location_id` int(10) unsigned NOT NULL,
  `fqdn` varchar(191) NOT NULL,
  `scheme` varchar(191) NOT NULL DEFAULT 'https',
  `behind_proxy` tinyint(1) NOT NULL DEFAULT 0,
  `maintenance_mode` tinyint(1) NOT NULL DEFAULT 0,
  `memory` int(10) unsigned NOT NULL,
  `memory_overallocate` int(11) NOT NULL DEFAULT 0,
  `disk` int(10) unsigned NOT NULL,
  `disk_overallocate` int(11) NOT NULL DEFAULT 0,
  `upload_size` int(10) unsigned NOT NULL DEFAULT 100,
  `daemon_token_id` char(16) NOT NULL,
  `daemon_token` text NOT NULL,
  `daemonListen` smallint(5) unsigned NOT NULL DEFAULT 8080,
  `daemonSFTP` smallint(5) unsigned NOT NULL DEFAULT 2022,
  `daemonBase` varchar(191) NOT NULL DEFAULT '/home/daemon-files',
  `created_at` timestamp NULL DEFAULT NULL,
  `updated_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `nodes_uuid_unique` (`uuid`),
  UNIQUE KEY `nodes_daemon_token_id_unique` (`daemon_token_id`),
  KEY `nodes_location_id_foreign` (`location_id`),
  CONSTRAINT `nodes_location_id_foreign` FOREIGN KEY (`location_id`) REFERENCES `locations` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `nests` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `uuid` char(36) NOT NULL,
  `author` char(191) NOT NULL,
  `name` varchar(191) NOT NULL,
  `description` text DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT NULL,
  `updated_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `services_uuid_unique` (`uuid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `eggs` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `uuid` char(36) NOT NULL,
  `nest_id` int(10) unsigned NOT NULL,
  `author` varchar(191) NOT NULL,
  `name` varchar(191) NOT NULL,
  `description` text DEFAULT NULL,
  `features` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`features`)),
  `docker_images` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`docker_images`)),
  `file_denylist` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`file_denylist`)),
  `update_url` text DEFAULT NULL,
  `config_files` text DEFAULT NULL,
  `config_startup` text DEFAULT NULL,
  `config_logs` text DEFAULT NULL,
  `config_stop` varchar(191) DEFAULT NULL,
  `config_from` int(10) unsigned DEFAULT NULL,
  `startup` text DEFAULT NULL,
  `script_container` varchar(191) NOT NULL DEFAULT 'alpine:3.4',
  `copy_script_from` int(10) unsigned DEFAULT NULL,
  `script_entry` varchar(191) NOT NULL DEFAULT 'ash',
  `script_is_privileged` tinyint(1) NOT NULL DEFAULT 1,
  `script_install` text DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT NULL,
  `updated_at` timestamp NULL DEFAULT NULL,
  `force_outgoing_ip` tinyint(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE KEY `service_options_uuid_unique` (`uuid`),
  KEY `service_options_nest_id_foreign` (`nest_id`),
  KEY `eggs_config_from_foreign` (`config_from`),
  KEY `eggs_copy_script_from_foreign` (`copy_script_from`),
  CONSTRAINT `eggs_config_from_foreign` FOREIGN KEY (`config_from`) REFERENCES `eggs` (`id`) ON DELETE SET NULL,
  CONSTRAINT `eggs_copy_script_from_foreign` FOREIGN KEY (`copy_script_from`) REFERENCES `eggs` (`id`) ON DELETE SET NULL,
  CONSTRAINT `service_options_nest_id_foreign` FOREIGN KEY (`nest_id`) REFERENCES `nests` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `egg_variables` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `egg_id` int(10) unsigned NOT NULL,
  `name` varchar(191) NOT NULL,
  `description` text NOT NULL,
  `env_variable` varchar(191) NOT NULL,
  `default_value` text NOT NULL,
  `user_viewable` tinyint(3) unsigned NOT NULL,
  `user_editable` tinyint(3) unsigned NOT NULL,
  `rules` text DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT NULL,
  `updated_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `service_variables_egg_id_foreign` (`egg_id`),
  CONSTRAINT `service_variables_egg_id_foreign` FOREIGN KEY (`egg_id`) REFERENCES `eggs` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    # 先不声明 allocations_server_id_foreign，待 servers 建表后再条件补齐以打破循环外键依赖。
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `allocations` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `node_id` int(10) unsigned NOT NULL,
  `ip` varchar(191) NOT NULL,
  `ip_alias` text DEFAULT NULL,
  `port` mediumint(8) unsigned NOT NULL,
  `server_id` int(10) unsigned DEFAULT NULL,
  `notes` varchar(191) DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT NULL,
  `updated_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `allocations_node_id_ip_port_unique` (`node_id`,`ip`,`port`),
  KEY `allocations_server_id_foreign` (`server_id`),
  CONSTRAINT `allocations_node_id_foreign` FOREIGN KEY (`node_id`) REFERENCES `nodes` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `servers` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `external_id` varchar(191) DEFAULT NULL,
  `uuid` char(36) NOT NULL,
  `uuidShort` char(8) NOT NULL,
  `node_id` int(10) unsigned NOT NULL,
  `name` varchar(191) NOT NULL,
  `description` text NOT NULL,
  `status` varchar(191) DEFAULT NULL,
  `skip_scripts` tinyint(1) NOT NULL DEFAULT 0,
  `owner_id` int(10) unsigned NOT NULL,
  `memory` int(10) unsigned NOT NULL,
  `swap` int(11) NOT NULL,
  `disk` int(10) unsigned NOT NULL,
  `io` int(10) unsigned NOT NULL,
  `cpu` int(10) unsigned NOT NULL,
  `threads` varchar(191) DEFAULT NULL,
  `oom_disabled` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `allocation_id` int(10) unsigned NOT NULL,
  `nest_id` int(10) unsigned NOT NULL,
  `egg_id` int(10) unsigned NOT NULL,
  `startup` text NOT NULL,
  `image` varchar(191) NOT NULL,
  `allocation_limit` int(10) unsigned DEFAULT NULL,
  `database_limit` int(10) unsigned DEFAULT 0,
  `backup_limit` int(10) unsigned NOT NULL DEFAULT 0,
  `created_at` timestamp NULL DEFAULT NULL,
  `updated_at` timestamp NULL DEFAULT NULL,
  `installed_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `servers_uuid_unique` (`uuid`),
  UNIQUE KEY `servers_uuidshort_unique` (`uuidShort`),
  UNIQUE KEY `servers_allocation_id_unique` (`allocation_id`),
  UNIQUE KEY `servers_external_id_unique` (`external_id`),
  KEY `servers_node_id_foreign` (`node_id`),
  KEY `servers_owner_id_foreign` (`owner_id`),
  KEY `servers_nest_id_foreign` (`nest_id`),
  KEY `servers_egg_id_foreign` (`egg_id`),
  CONSTRAINT `servers_allocation_id_foreign` FOREIGN KEY (`allocation_id`) REFERENCES `allocations` (`id`),
  CONSTRAINT `servers_egg_id_foreign` FOREIGN KEY (`egg_id`) REFERENCES `eggs` (`id`),
  CONSTRAINT `servers_nest_id_foreign` FOREIGN KEY (`nest_id`) REFERENCES `nests` (`id`),
  CONSTRAINT `servers_node_id_foreign` FOREIGN KEY (`node_id`) REFERENCES `nodes` (`id`),
  CONSTRAINT `servers_owner_id_foreign` FOREIGN KEY (`owner_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )

    if context.is_offline_mode():
        need_alloc_server_fk = True
    else:
        bind = op.get_bind()
        need_alloc_server_fk = (
            bind.execute(
                sa.text(
                    """
                    SELECT 1
                    FROM information_schema.TABLE_CONSTRAINTS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = 'allocations'
                      AND CONSTRAINT_NAME = 'allocations_server_id_foreign'
                      AND CONSTRAINT_TYPE = 'FOREIGN KEY'
                    LIMIT 1
                    """
                )
            ).scalar()
            is None
        )
    if need_alloc_server_fk:
        op.execute(
            """
ALTER TABLE `allocations`
  ADD CONSTRAINT `allocations_server_id_foreign`
  FOREIGN KEY (`server_id`) REFERENCES `servers` (`id`) ON DELETE SET NULL
            """
        )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS `server_variables` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `server_id` int(10) unsigned DEFAULT NULL,
  `variable_id` int(10) unsigned NOT NULL,
  `variable_value` text NOT NULL,
  `created_at` timestamp NULL DEFAULT NULL,
  `updated_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `server_variables_server_id_foreign` (`server_id`),
  KEY `server_variables_variable_id_foreign` (`variable_id`),
  CONSTRAINT `server_variables_server_id_foreign` FOREIGN KEY (`server_id`) REFERENCES `servers` (`id`) ON DELETE CASCADE,
  CONSTRAINT `server_variables_variable_id_foreign` FOREIGN KEY (`variable_id`) REFERENCES `egg_variables` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `activity_logs` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `batch` char(36) DEFAULT NULL,
  `event` varchar(191) NOT NULL,
  `ip` varchar(191) NOT NULL,
  `description` text DEFAULT NULL,
  `actor_type` varchar(191) DEFAULT NULL,
  `actor_id` bigint(20) unsigned DEFAULT NULL,
  `api_key_id` int(10) unsigned DEFAULT NULL,
  `properties` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`properties`)),
  `timestamp` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `activity_logs_actor_type_actor_id_index` (`actor_type`,`actor_id`),
  KEY `activity_logs_event_index` (`event`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `activity_log_subjects` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `activity_log_id` bigint(20) unsigned NOT NULL,
  `subject_type` varchar(191) NOT NULL,
  `subject_id` bigint(20) unsigned NOT NULL,
  PRIMARY KEY (`id`),
  KEY `activity_log_subjects_activity_log_id_foreign` (`activity_log_id`),
  KEY `activity_log_subjects_subject_type_subject_id_index` (`subject_type`,`subject_id`),
  CONSTRAINT `activity_log_subjects_activity_log_id_foreign` FOREIGN KEY (`activity_log_id`) REFERENCES `activity_logs` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `backups` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `server_id` int(10) unsigned NOT NULL,
  `uuid` char(36) NOT NULL,
  `upload_id` text DEFAULT NULL,
  `is_successful` tinyint(1) NOT NULL DEFAULT 0,
  `is_locked` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `name` varchar(191) NOT NULL,
  `ignored_files` text NOT NULL,
  `disk` varchar(191) NOT NULL,
  `checksum` varchar(191) DEFAULT NULL,
  `bytes` bigint(20) unsigned NOT NULL DEFAULT 0,
  `completed_at` timestamp NULL DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT NULL,
  `updated_at` timestamp NULL DEFAULT NULL,
  `deleted_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `backups_uuid_unique` (`uuid`),
  KEY `backups_server_id_foreign` (`server_id`),
  CONSTRAINT `backups_server_id_foreign` FOREIGN KEY (`server_id`) REFERENCES `servers` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `user_ssh_keys` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `user_id` int(10) unsigned NOT NULL,
  `name` varchar(191) NOT NULL,
  `fingerprint` varchar(191) NOT NULL,
  `public_key` text NOT NULL,
  `created_at` timestamp NULL DEFAULT NULL,
  `updated_at` timestamp NULL DEFAULT NULL,
  `deleted_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `user_ssh_keys_user_id_foreign` (`user_id`),
  CONSTRAINT `user_ssh_keys_user_id_foreign` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `subusers` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `user_id` int(10) unsigned NOT NULL,
  `server_id` int(10) unsigned NOT NULL,
  `permissions` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`permissions`)),
  `created_at` timestamp NULL DEFAULT NULL,
  `updated_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `subusers_user_id_foreign` (`user_id`),
  KEY `subusers_server_id_foreign` (`server_id`),
  CONSTRAINT `subusers_server_id_foreign` FOREIGN KEY (`server_id`) REFERENCES `servers` (`id`) ON DELETE CASCADE,
  CONSTRAINT `subusers_user_id_foreign` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `server_transfers` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `server_id` int(10) unsigned NOT NULL,
  `successful` tinyint(1) DEFAULT NULL,
  `old_node` int(10) unsigned NOT NULL,
  `new_node` int(10) unsigned NOT NULL,
  `old_allocation` int(10) unsigned NOT NULL,
  `new_allocation` int(10) unsigned NOT NULL,
  `old_additional_allocations` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`old_additional_allocations`)),
  `new_additional_allocations` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`new_additional_allocations`)),
  `archived` tinyint(1) NOT NULL DEFAULT 0,
  `created_at` timestamp NULL DEFAULT NULL,
  `updated_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `server_transfers_server_id_foreign` (`server_id`),
  CONSTRAINT `server_transfers_server_id_foreign` FOREIGN KEY (`server_id`) REFERENCES `servers` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `mounts` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `uuid` char(36) NOT NULL,
  `name` varchar(191) NOT NULL,
  `description` text DEFAULT NULL,
  `source` varchar(191) NOT NULL,
  `target` varchar(191) NOT NULL,
  `read_only` tinyint(3) unsigned NOT NULL,
  `user_mountable` tinyint(3) unsigned NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `mounts_id_unique` (`id`),
  UNIQUE KEY `mounts_uuid_unique` (`uuid`),
  UNIQUE KEY `mounts_name_unique` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `mount_server` (
  `server_id` int(10) unsigned NOT NULL,
  `mount_id` int(10) unsigned NOT NULL,
  UNIQUE KEY `mount_server_server_id_mount_id_unique` (`server_id`,`mount_id`),
  KEY `mount_server_mount_id_foreign` (`mount_id`),
  CONSTRAINT `mount_server_mount_id_foreign` FOREIGN KEY (`mount_id`) REFERENCES `mounts` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `mount_server_server_id_foreign` FOREIGN KEY (`server_id`) REFERENCES `servers` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS `mount_node` (
  `node_id` int(10) unsigned NOT NULL,
  `mount_id` int(10) unsigned NOT NULL,
  UNIQUE KEY `mount_node_node_id_mount_id_unique` (`node_id`,`mount_id`),
  KEY `mount_node_mount_id_foreign` (`mount_id`),
  CONSTRAINT `mount_node_mount_id_foreign` FOREIGN KEY (`mount_id`) REFERENCES `mounts` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `mount_node_node_id_foreign` FOREIGN KEY (`node_id`) REFERENCES `nodes` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )


def downgrade() -> None:
    raise RuntimeError("Refusing to drop core tables in baseline downgrade")
