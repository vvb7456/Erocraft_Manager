"""Trial plan type + convert order kind.

Adds:

* ``manager_billing_plans.plan_type`` (standard|trial) + ``linked_plan_id``
  (trial → the standard plan whose resources it mirrors).
* ``manager_server_meta.is_trial`` — snapshot flag set at apply time so a
  trial server stays identifiable even if its plan row is later deleted.
* ``users.has_owned_server`` — permanent per-user flag (set on first server
  ownership via ANY path: paid order, admin manual create, import). Drives
  the "trial plans only for users who never owned a server" rule, which
  can't rely on order history because most servers are admin-created from
  off-platform sales and leave no order row.
* ``manager_billing_orders.kind`` + ``manager_billing_order_effects.effect_type``
  gain the ``convert`` value (trial → its linked standard plan).

Backfill: ``users.has_owned_server`` is seeded from ``servers.owner_id`` so
all currently-existing owners are marked. This is a one-way flag; it is
never reset, even if the server is later deleted.
"""

from __future__ import annotations

from alembic import op


revision = "20260619_trial"
down_revision = "20260524_coupons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── manager_billing_plans: plan_type + linked_plan_id ────────────────
    op.execute(
        """
ALTER TABLE `manager_billing_plans`
  ADD COLUMN `plan_type` varchar(16) NOT NULL DEFAULT 'standard' AFTER `category_label`,
  ADD COLUMN `linked_plan_id` bigint(20) DEFAULT NULL AFTER `plan_type`,
  ADD KEY `idx_billing_plans_type` (`plan_type`),
  ADD KEY `fk_billing_plans_linked` (`linked_plan_id`),
  ADD CONSTRAINT `fk_billing_plans_linked` FOREIGN KEY (`linked_plan_id`) REFERENCES `manager_billing_plans` (`id`) ON DELETE SET NULL,
  ADD CONSTRAINT `chk_billing_plans_type` CHECK (`plan_type` IN ('standard','trial'))
        """
    )
    # NOTE: a CHECK tying plan_type='trial' => linked_plan_id NOT NULL is
    # not possible in MySQL 8 because ``linked_plan_id`` is also a FK
    # column (MySQL rejects FK columns in CHECK expressions, error 1901).
    # That invariant is enforced in app/services/billing/plans.py instead.

    # ── manager_server_meta: is_trial ────────────────────────────────────
    op.execute(
        """
ALTER TABLE `manager_server_meta`
  ADD COLUMN `is_trial` tinyint(1) NOT NULL DEFAULT 0 AFTER `plan_id`
        """
    )

    # ── users.has_owned_server (Pterodactyl panel table) ─────────────────
    # NOT NULL default 0; backfilled below.
    op.execute(
        """
ALTER TABLE `users`
  ADD COLUMN `has_owned_server` tinyint(1) NOT NULL DEFAULT 0 AFTER `root_admin`
        """
    )
    op.execute(
        """
UPDATE `users` u
SET u.`has_owned_server` = 1
WHERE EXISTS (SELECT 1 FROM `servers` s WHERE s.`owner_id` = u.`id`)
        """
    )

    # ── orders.kind + effects.effect_type: add 'convert' ─────────────────
    # convert = trial → linked standard plan renewal (only valid trial path).
    op.execute(
        """
ALTER TABLE `manager_billing_orders`
  MODIFY COLUMN `kind` enum('renew','new_purchase','upgrade','convert') NOT NULL
        """
    )
    # Extend the renew-target CHECK so convert also requires target_server_id.
    op.execute(
        "ALTER TABLE `manager_billing_orders` DROP CONSTRAINT `chk_billing_orders_renew_target`"
    )
    op.execute(
        """
ALTER TABLE `manager_billing_orders`
  ADD CONSTRAINT `chk_billing_orders_target_required`
  CHECK (
    `kind` NOT IN ('renew','convert') OR `target_server_id` IS NOT NULL
  )
        """
    )
    op.execute(
        """
ALTER TABLE `manager_billing_order_effects`
  MODIFY COLUMN `effect_type` enum('renew','new_purchase','upgrade','convert') NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
ALTER TABLE `manager_billing_order_effects`
  MODIFY COLUMN `effect_type` enum('renew','new_purchase','upgrade') NOT NULL
        """
    )
    op.execute(
        "ALTER TABLE `manager_billing_orders` DROP CONSTRAINT `chk_billing_orders_target_required`"
    )
    op.execute(
        """
ALTER TABLE `manager_billing_orders`
  ADD CONSTRAINT `chk_billing_orders_renew_target`
  CHECK (`kind` <> 'renew' or `target_server_id` is not null)
        """
    )
    op.execute(
        """
ALTER TABLE `manager_billing_orders`
  MODIFY COLUMN `kind` enum('renew','new_purchase','upgrade') NOT NULL
        """
    )
    op.execute("ALTER TABLE `users` DROP COLUMN `has_owned_server`")
    op.execute("ALTER TABLE `manager_server_meta` DROP COLUMN `is_trial`")
    op.execute(
        """
ALTER TABLE `manager_billing_plans`
  DROP CONSTRAINT `chk_billing_plans_type`,
  DROP FOREIGN KEY `fk_billing_plans_linked`,
  DROP KEY `fk_billing_plans_linked`,
  DROP KEY `idx_billing_plans_type`,
  DROP COLUMN `linked_plan_id`,
  DROP COLUMN `plan_type`
        """
    )
