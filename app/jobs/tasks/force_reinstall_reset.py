"""Reset FORCE_REINSTALL=true back to false once Wings finishes the install.

When a force reinstall is triggered (admin or user), the manager sets
``FORCE_REINSTALL=true`` in ``panel.server_variables`` so the install
script wipes ``/home/container``. That flag must be cleared after install
completes; otherwise every subsequent *normal* reinstall would silently
wipe user data.

The reinstall route used to do this in a ``finally`` block, but that
fired within milliseconds of triggering Wings — long before the install
container actually pulled its env from panel. The script then read
``FORCE_REINSTALL=false`` and skipped the wipe.

Detection here is simple and idempotent: any server whose ``status IS
NULL`` (= installed/idle, not currently ``installing``) and has a
``FORCE_REINSTALL=true`` row in ``server_variables`` is eligible. Wings
sets ``status=NULL`` + ``installed_at=NOW()`` via the daemon → panel
callback when install finishes, so this filter naturally waits until
install completion. No bespoke per-server flag needed.

If a user triggers force reinstall a second time before this scan runs
(rare race), ``mark_for_reinstall`` writes ``status='installing'`` first,
so the row is excluded from this scan. Safe.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from app.db.session import get_session_factory
from app.services.audit import log_manager_activity

logger = logging.getLogger(__name__)

FORCE_REINSTALL_RESET_JOB_ID = "force_reinstall_reset"

_SCAN_AND_RESET_SQL = text(
    """
    UPDATE server_variables sv
    JOIN servers s        ON s.id = sv.server_id
    JOIN egg_variables ev ON ev.id = sv.variable_id
    SET sv.variable_value = 'false',
        sv.updated_at = NOW()
    WHERE ev.env_variable = 'FORCE_REINSTALL'
      AND sv.variable_value = 'true'
      AND s.status IS NULL
      AND s.installed_at IS NOT NULL
    """
)


async def run_force_reinstall_reset() -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        result = await db.execute(_SCAN_AND_RESET_SQL)
        await db.commit()
        n = result.rowcount or 0
        if n:
            logger.info("force_reinstall_reset: cleared FORCE_REINSTALL on %d server(s)", n)
            await log_manager_activity(
                db,
                actor="system",
                category="lifecycle",
                status="success",
                detail_key="force_reinstall_reset.cleared",
                detail_params={"count": int(n)},
            )
            await db.commit()
