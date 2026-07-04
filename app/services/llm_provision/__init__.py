"""LLM subscription provision / sync service.

Each LLM-enabled server gets its own NewAPI user with a native
subscription. Quota enforcement and monthly reset are handled by
NewAPI's background tasks; Manager only manages the user/subscription/
token lifecycle and reads usage at display time.
"""

from app.services.llm_provision.provision import (
    provision_for_server,
    revoke_for_server,
    update_for_upgrade,
)
from app.services.llm_provision.sync import run_llm_daily_sync

__all__ = [
    "provision_for_server",
    "revoke_for_server",
    "update_for_upgrade",
    "run_llm_daily_sync",
]
