"""Coupon templates / coupons / invite codes / referrals.

See ``docs/REFERRAL_AND_COUPON_DESIGN.md`` §4 + §16. Adds:

* ``manager_user_invite_codes`` — 1:1 per user, lazy-generated.
* ``manager_billing_coupon_templates`` — admin-defined rule sources.
* ``manager_billing_coupons`` — per-user issued instances with snapshot fields.
* ``manager_user_referrals`` — inviter / invitee binding + reward audit.
* ``manager_pending_registrations`` gains ``inviter_user_id`` + ``invite_code``.
* ``manager_billing_orders`` gains ``coupon_id`` + ``coupon_discount_fen``.
* Seeds two built-in coupon templates (``REFERRAL_INVITER``, ``REFERRAL_INVITEE``).
"""

from __future__ import annotations

from alembic import op


revision = "20260524_coupons"
down_revision = "20260507_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE `manager_user_invite_codes` (
  `user_id` int(11) NOT NULL,
  `code` char(8) NOT NULL,
  `disabled_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`user_id`),
  UNIQUE KEY `uk_invite_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_billing_coupon_templates` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `code` varchar(64) NOT NULL,
  `name` varchar(128) NOT NULL,
  `description` text DEFAULT NULL,
  `discount_fen` int(11) NOT NULL,
  `min_order_fen` int(11) NOT NULL DEFAULT 0,
  `valid_days` int(11) NOT NULL DEFAULT 30,
  `applicable_plan_ids` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`applicable_plan_ids`)),
  `applicable_order_kinds` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`applicable_order_kinds`)),
  `is_active` tinyint(1) NOT NULL DEFAULT 1,
  `is_builtin` tinyint(1) NOT NULL DEFAULT 0,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_coupon_tpl_code` (`code`),
  KEY `idx_coupon_tpl_active` (`is_active`),
  CONSTRAINT `chk_coupon_tpl_discount_pos` CHECK (`discount_fen` > 0),
  CONSTRAINT `chk_coupon_tpl_min_nonneg` CHECK (`min_order_fen` >= 0),
  CONSTRAINT `chk_coupon_tpl_valid_days_pos` CHECK (`valid_days` > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_billing_coupons` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `code` char(16) NOT NULL,
  `template_id` bigint(20) NOT NULL,
  `user_id` int(11) NOT NULL,
  `source` enum('referral_inviter','referral_invitee','admin_grant','promo') NOT NULL,
  `source_ref_id` bigint(20) DEFAULT NULL,
  `status` enum('unused','reserved','used','revoked') NOT NULL DEFAULT 'unused',
  `discount_fen` int(11) NOT NULL,
  `min_order_fen` int(11) NOT NULL DEFAULT 0,
  `applicable_plan_ids` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`applicable_plan_ids`)),
  `applicable_order_kinds` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`applicable_order_kinds`)),
  `issued_at` datetime NOT NULL DEFAULT current_timestamp(),
  `expires_at` datetime NOT NULL,
  `reserved_order_id` bigint(20) DEFAULT NULL,
  `reserved_at` datetime DEFAULT NULL,
  `used_order_id` bigint(20) DEFAULT NULL,
  `used_at` datetime DEFAULT NULL,
  `actual_discount_fen` int(11) DEFAULT NULL,
  `revoked_at` datetime DEFAULT NULL,
  `revoked_by` int(11) DEFAULT NULL,
  `revoke_reason` varchar(255) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_coupon_code` (`code`),
  UNIQUE KEY `uk_coupon_reserved_order` (`reserved_order_id`),
  KEY `idx_coupon_user_status` (`user_id`,`status`,`expires_at`),
  KEY `idx_coupon_template` (`template_id`),
  KEY `idx_coupon_status_expires` (`status`,`expires_at`),
  KEY `idx_coupon_source_ref` (`source`,`source_ref_id`),
  CONSTRAINT `fk_coupon_template` FOREIGN KEY (`template_id`) REFERENCES `manager_billing_coupon_templates` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `chk_coupon_discount_pos` CHECK (`discount_fen` > 0),
  CONSTRAINT `chk_coupon_min_nonneg` CHECK (`min_order_fen` >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
CREATE TABLE `manager_user_referrals` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `inviter_user_id` int(11) NOT NULL,
  `invitee_user_id` int(11) NOT NULL,
  `invite_code` char(8) NOT NULL,
  `status` enum('registered','rewarded','revoked') NOT NULL DEFAULT 'registered',
  `qualifying_order_id` bigint(20) DEFAULT NULL,
  `rewarded_at` datetime DEFAULT NULL,
  `inviter_coupon_id` bigint(20) DEFAULT NULL,
  `invitee_coupon_id` bigint(20) DEFAULT NULL,
  `revoked_at` datetime DEFAULT NULL,
  `revoked_by` int(11) DEFAULT NULL,
  `revoke_reason` varchar(255) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_referral_invitee` (`invitee_user_id`),
  KEY `idx_referral_inviter_status` (`inviter_user_id`,`status`),
  KEY `idx_referral_qualifying_order` (`qualifying_order_id`),
  CONSTRAINT `fk_referral_inviter_coupon` FOREIGN KEY (`inviter_coupon_id`) REFERENCES `manager_billing_coupons` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_referral_invitee_coupon` FOREIGN KEY (`invitee_coupon_id`) REFERENCES `manager_billing_coupons` (`id`) ON DELETE SET NULL,
  CONSTRAINT `chk_referral_no_self` CHECK (`inviter_user_id` <> `invitee_user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )

    # ── ALTERs ───────────────────────────────────────────────────────────
    op.execute(
        """
ALTER TABLE `manager_pending_registrations`
  ADD COLUMN `inviter_user_id` int(11) DEFAULT NULL AFTER `lookup_hash`,
  ADD COLUMN `invite_code` char(8) DEFAULT NULL AFTER `inviter_user_id`,
  ADD KEY `idx_pr_inviter` (`inviter_user_id`)
        """
    )
    op.execute(
        """
ALTER TABLE `manager_billing_orders`
  ADD COLUMN `coupon_id` bigint(20) DEFAULT NULL AFTER `total_days`,
  ADD COLUMN `coupon_discount_fen` int(11) NOT NULL DEFAULT 0 AFTER `coupon_id`,
  ADD KEY `idx_billing_orders_coupon` (`coupon_id`),
  ADD CONSTRAINT `fk_billing_orders_coupon` FOREIGN KEY (`coupon_id`) REFERENCES `manager_billing_coupons` (`id`) ON DELETE SET NULL,
  ADD CONSTRAINT `chk_billing_orders_coupon_discount_nonneg` CHECK (`coupon_discount_fen` >= 0)
        """
    )

    # ── Seed built-in templates ──────────────────────────────────────────
    op.execute(
        """
INSERT INTO `manager_billing_coupon_templates`
  (`code`, `name`, `description`, `discount_fen`, `min_order_fen`,
   `valid_days`, `applicable_plan_ids`, `applicable_order_kinds`,
   `is_active`, `is_builtin`)
VALUES
  ('REFERRAL_INVITER', '邀请奖励券',
   '邀请新用户完成首单后自动发放给邀请人',
   500, 0, 30, NULL, NULL, 1, 1),
  ('REFERRAL_INVITEE', '新人欢迎券',
   '通过邀请注册的新用户完成首单后获得',
   500, 0, 30, NULL, NULL, 1, 1)
        """
    )


def downgrade() -> None:
    op.execute(
        """
ALTER TABLE `manager_billing_orders`
  DROP FOREIGN KEY `fk_billing_orders_coupon`,
  DROP CONSTRAINT `chk_billing_orders_coupon_discount_nonneg`,
  DROP KEY `idx_billing_orders_coupon`,
  DROP COLUMN `coupon_discount_fen`,
  DROP COLUMN `coupon_id`
        """
    )
    op.execute(
        """
ALTER TABLE `manager_pending_registrations`
  DROP KEY `idx_pr_inviter`,
  DROP COLUMN `invite_code`,
  DROP COLUMN `inviter_user_id`
        """
    )
    op.execute("DROP TABLE IF EXISTS `manager_user_referrals`")
    op.execute("DROP TABLE IF EXISTS `manager_billing_coupons`")
    op.execute("DROP TABLE IF EXISTS `manager_billing_coupon_templates`")
    op.execute("DROP TABLE IF EXISTS `manager_user_invite_codes`")
