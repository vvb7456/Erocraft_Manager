"""Command executor: dispatch by type → handler.

Phase 1 only implements `ping`. Other types return 501-equivalent error.
"""

from __future__ import annotations

import time

from ..schemas import CommandRequest, CommandResponse
from . import handlers


HANDLERS = {
    "ping": handlers.ping,
    "wings.restart": handlers.wings_restart,
    "wings.status": handlers.wings_status,
}


async def execute(req: CommandRequest) -> CommandResponse:
    start = time.monotonic()
    handler = HANDLERS.get(req.type)
    if handler is None:
        return CommandResponse(
            id=req.id,
            ok=False,
            error=f"command type not implemented in this agent version: {req.type}",
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    try:
        output = await handler(req.params or {})
        return CommandResponse(
            id=req.id,
            ok=True,
            output=output,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    except Exception as e:
        return CommandResponse(
            id=req.id,
            ok=False,
            error=str(e)[:500],
            duration_ms=int((time.monotonic() - start) * 1000),
        )
