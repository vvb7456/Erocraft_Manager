"""User agreements: documents, versions, acceptances.

Adds three new tables implementing the user-agreement system described in
``docs/USER_AGREEMENT_DESIGN.md``:

* ``manager_agreements`` — agreement document definitions (slug, scope,
  require_register/purchase flags, current_version pointer).
* ``manager_agreement_versions`` — bilingual versioned Markdown bodies.
  Re-consent is triggered by bumping ``manager_agreements.current_version``
  (which points at a row here); a patch-in-place updates this row's body
  without bumping and therefore without triggering re-consent.
* ``manager_user_agreement_acceptances`` — who consented to which version
  in which context. ``UNIQUE(user_id, agreement_id, version)`` makes
  repeat submissions idempotent.

Also adds ``manager_pending_registrations.agreements_json`` so the
two-stage registration flow can carry the consent intent from the form
submit through to the verify step (where the real ``user.id`` finally
exists and the acceptance rows are materialized).

Optional seed: two global agreements ``tos`` and ``privacy`` with
``require_register=1`` and ``current_version=0`` (no version published yet
— the admin publishes the first version from the management UI).
"""

from __future__ import annotations

from alembic import op


revision = "20260718_agreements"
down_revision = "20260622_llm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── manager_agreements ────────────────────────────────────────────────
    op.execute(
        """
CREATE TABLE `manager_agreements` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `slug` varchar(32) NOT NULL,
  `scope` varchar(16) NOT NULL DEFAULT 'global',
  `egg_id` int(11) DEFAULT NULL,
  `require_register` tinyint(1) NOT NULL DEFAULT 0,
  `require_purchase` tinyint(1) NOT NULL DEFAULT 0,
  `is_enabled` tinyint(1) NOT NULL DEFAULT 1,
  `sort_order` int(11) NOT NULL DEFAULT 0,
  `current_version` int(11) NOT NULL DEFAULT 0,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_agreement_slug` (`slug`),
  KEY `idx_agreement_scope` (`scope`),
  KEY `idx_agreement_enabled` (`is_enabled`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )

    # ── manager_agreement_versions ───────────────────────────────────────
    op.execute(
        """
CREATE TABLE `manager_agreement_versions` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `agreement_id` int(11) NOT NULL,
  `version` int(11) NOT NULL,
  `title_zh` varchar(191) NOT NULL DEFAULT '',
  `title_en` varchar(191) NOT NULL DEFAULT '',
  `body_zh` mediumtext NOT NULL,
  `body_en` mediumtext NOT NULL,
  `published_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `published_by` varchar(100) NOT NULL DEFAULT '',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_agreement_version` (`agreement_id`, `version`),
  KEY `idx_agreement_version_agreement` (`agreement_id`),
  CONSTRAINT `fk_agreement_version_agreement` FOREIGN KEY (`agreement_id`)
      REFERENCES `manager_agreements` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )

    # ── manager_user_agreement_acceptances ───────────────────────────────
    op.execute(
        """
CREATE TABLE `manager_user_agreement_acceptances` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `agreement_id` int(11) NOT NULL,
  `slug` varchar(32) NOT NULL,
  `version` int(11) NOT NULL,
  `context` varchar(16) NOT NULL,
  `order_id` bigint(20) DEFAULT NULL,
  `locale` varchar(8) DEFAULT NULL,
  `ip` varchar(64) DEFAULT NULL,
  `accepted_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_agreement_acceptance` (`user_id`, `agreement_id`, `version`),
  KEY `idx_agreement_acceptance_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )

    # ── manager_pending_registrations.agreements_json ────────────────────
    op.execute(
        """
ALTER TABLE `manager_pending_registrations`
  ADD COLUMN `agreements_json` json DEFAULT NULL AFTER `invite_code`
        """
    )

    # ── Seed tos + privacy global agreements (require_register, no version) ─
    op.execute(
        """
INSERT INTO `manager_agreements`
    (`slug`, `scope`, `require_register`, `require_purchase`, `sort_order`)
VALUES
    ('tos', 'global', 1, 0, 0),
    ('privacy', 'global', 1, 0, 1)
        """
    )

    # ── Backfill acceptances for existing users ──────────────────────────
    # Treat every existing panel user as having consented to v1 of both
    # global agreements, using a sentinel ``accepted_at='1970-01-01'`` so
    # these placeholder rows are visually distinguishable from real
    # consent records. When an admin later publishes v1 (bump),
    # ``current_version`` becomes 1 and these rows match — no re-consent
    # triggered for存量 users. If the admin bumps straight to v2, the
    # stored version (1) is less than current (2) and the re-consent gate
    # fires, which is the desired behavior.
    #
    # INSERT IGNORE keeps this idempotent against re-runs (the UNIQUE on
    # user_id+agreement_id+version skips rows that already exist).
    op.execute(
        """
INSERT IGNORE INTO `manager_user_agreement_acceptances`
    (`user_id`, `agreement_id`, `slug`, `version`, `context`, `accepted_at`)
SELECT u.`id`, a.`id`, a.`slug`, 1, 'register', '1970-01-01 00:00:00'
FROM `users` u
CROSS JOIN `manager_agreements` a
WHERE a.`slug` IN ('tos', 'privacy')
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE `manager_pending_registrations` DROP COLUMN `agreements_json`"
    )
    op.execute("DROP TABLE IF EXISTS `manager_user_agreement_acceptances`")
    op.execute("DROP TABLE IF EXISTS `manager_agreement_versions`")
    op.execute("DROP TABLE IF EXISTS `manager_agreements`")
