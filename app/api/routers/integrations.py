"""Integrations: small proxies for third-party APIs that would otherwise
be hit directly from the user's browser.

Currently exposes:
- ``GET /integrations/sillytavern/tags`` — list of recent SillyTavern git
  tags, mirrored from GitHub with a 1-hour in-process cache. Avoids the
  unauthenticated 60-req/hour-per-IP limit that hits users' browsers
  when many tabs reload the egg-settings page in quick succession.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends

from app.api.deps.auth import get_current_user
from app.db.models.pterodactyl import PteroUser

router = APIRouter(prefix="/integrations", tags=["integrations"])
logger = logging.getLogger(__name__)

_GITHUB_URL = "https://api.github.com/repos/SillyTavern/SillyTavern/tags?per_page=50"
_TTL_SECONDS = 3600  # 1 hour
_TIMEOUT_SECONDS = 5.0

# Process-level cache. Web runs as a single uvicorn worker (see
# manager.sh) so a plain dict is sufficient. If we ever scale to N
# workers each will fetch independently — still well under the 60
# req/hr quota.
_cache: dict[str, Any] = {
    "tags": [],
    "fetched_at": 0.0,
}


async def _fetch_from_github() -> list[str] | None:
    """Fetch tag names from GitHub. Returns None on any failure."""
    headers = {
        "User-Agent": "erocraft-manager",
        "Accept": "application/vnd.github+json",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, trust_env=False) as client:
            resp = await client.get(_GITHUB_URL, headers=headers)
        if resp.status_code != 200:
            logger.warning("sillytavern tags fetch: github returned %s", resp.status_code)
            return None
        payload = resp.json()
        return [item["name"] for item in payload if isinstance(item, dict) and "name" in item]
    except Exception as exc:  # noqa: BLE001
        logger.warning("sillytavern tags fetch failed: %s", exc)
        return None


@router.get("/sillytavern/tags")
async def sillytavern_tags(
    _: PteroUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return recent SillyTavern git tags. Cached for 1 hour.

    Response shape::

        { "tags": ["1.13.5", "1.13.4", ...], "stale": false }

    On GitHub failure with no prior cache, returns ``{"tags": [], "stale": true}``
    so the frontend can fall back to its hard-coded ``release``/``staging``
    options without surfacing an error.
    """
    now = time.time()
    age = now - float(_cache.get("fetched_at") or 0)

    if _cache["tags"] and age < _TTL_SECONDS:
        return {"tags": _cache["tags"], "stale": False}

    tags = await _fetch_from_github()
    if tags is not None:
        _cache["tags"] = tags
        _cache["fetched_at"] = now
        return {"tags": tags, "stale": False}

    # GitHub failed — return the stale cache if we have one.
    if _cache["tags"]:
        return {"tags": _cache["tags"], "stale": True}
    return {"tags": [], "stale": True}
