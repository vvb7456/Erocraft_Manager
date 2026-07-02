"""LLM free quota provision / sync service.

See ``docs/LLM_FREE_QUOTA_DESIGN.md`` for the full design.

Config injection into SillyTavern is handled entirely by the egg —
Manager only creates the NewAPI token and stores the key locally.
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
