"""Enforce one-active-order-per-user via virtual column + unique index.

Background
----------
Earlier code checked "user can only have one open order" purely in Python
(``_check_no_pending_order`` + a post-INSERT race tie-break). Two
concurrent ``POST /api/user/orders`` requests could both pass the
pre-INSERT check, both INSERT, and the tie-break used the wrong limit
constant — so users could end up with multiple ``pending`` orders and
multiple placeholder servers occupying allocations.

Fix
---
Add a VIRTUAL generated column ``active_user_lock`` that equals
``user_id`` while ``status`` is one of ``pending / processing /
manual_review`` and ``NULL`` otherwise, plus a UNIQUE index on it.
``NULL`` values do not collide under MySQL/MariaDB UNIQUE semantics, so
finished orders impose no constraint. Database guarantees what Python
cannot under concurrent inserts.

Preflight: abort if any user already has more than one such row, so
production data anomalies surface to ops before the new index lands.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "20260505_orders_active_lock"
down_revision = "20260504_upgrade_td_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # Preflight: detect duplicates before adding the unique index.
    dupes = bind.execute(
        text(
            """
            SELECT user_id, COUNT(*) AS n
            FROM manager_billing_orders
            WHERE status IN ('pending','processing','manual_review')
            GROUP BY user_id
            HAVING n > 1
            """
        )
    ).fetchall()
    if dupes:
        rows = ", ".join(f"user_id={r.user_id}(n={r.n})" for r in dupes)
        raise RuntimeError(
            "Cannot add unique constraint manager_billing_orders.active_user_lock: "
            f"existing duplicate active orders detected ({rows}). "
            "Resolve manually (cancel/close older ones) and re-run the migration."
        )

    op.execute(
        """
        ALTER TABLE manager_billing_orders
        ADD COLUMN active_user_lock INT
            GENERATED ALWAYS AS
                (CASE WHEN status IN ('pending','processing','manual_review')
                      THEN user_id END)
            VIRTUAL
        """
    )
    op.execute(
        """
        ALTER TABLE manager_billing_orders
        ADD UNIQUE KEY uk_billing_orders_active_user (active_user_lock)
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE manager_billing_orders DROP INDEX uk_billing_orders_active_user"
    )
    op.execute(
        "ALTER TABLE manager_billing_orders DROP COLUMN active_user_lock"
    )
