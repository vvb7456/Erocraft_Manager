"""Wings configuration management — direct write to ``panel.nodes`` + push to
wings ``POST /api/update``.

Replaces the legacy Application API → ``wings configure`` round-trip
(see ``docs/MONITORING_AND_AGENT.md`` §11.1, v3.1 path). Agent is **not**
involved in the main edit path: manager talks to wings HTTP directly.

Design principle (v3.1 / PR-A): ``panel.nodes`` is the single source of truth.
The legacy "drift detection" (compare panel value vs wings YAML on disk) was
intentionally removed because:

1. It compared persisted YAML, not the running wings process — after a PUT,
   the YAML matches but a runtime-restart-required field (port, scheme, sftp,
   data dir) is still bound to the old value, leading to a misleading
   "all consistent" UI signal.
2. The only realistic case it caught (operator SSHs in and edits wings YAML
   by hand) is already a process violation in the v3 architecture; the next
   manager push overwrites the change anyway.

Instead, the surface now offers:

* :func:`get_state` — returns the panel snapshot plus the wings systemd
  status (so the UI can show "wings was restarted at X"). No drift.
* :func:`push_to_wings` / PUT response — includes the subset of changed
  fields that require a wings restart to take effect, so the UI can show
  a banner prompting the operator to click "restart wings".
* The standalone ``/agent/wings-config`` endpoint remains as a manual
  diagnostic tool when an operator suspects out-of-band tampering.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pterodactyl import PanelNode
from app.services import agent_client, host_registry
from app.services.wings import WingsServiceError, wings_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# White-list of fields editable via this surface (panel.nodes column names)
# ---------------------------------------------------------------------------

#: Fields that wings actually consumes (mapped into wings Configuration).
#:
#: NOTE: ``fqdn`` is intentionally **not** here. Wings ``api.host`` is hard-
#: coded to ``0.0.0.0`` and the FQDN is only used by panel for URL generation
#: / cert provisioning. Including fqdn here would force a daemon_token
#: decryption + a content-less ``/api/update`` push (just token + token_id)
#: on every panel-only label change — useless work that also makes a pure
#: panel edit fail with 500 when ``PANEL_APP_KEY`` is missing or the cipher
#: is corrupt. fqdn lives in :data:`PANEL_ONLY_FIELDS` instead.
WINGS_AFFECTING_FIELDS: tuple[str, ...] = (
    "scheme",
    "behind_proxy",
    "upload_size",
    "daemon_listen",
    "daemon_sftp",
    "daemon_base",
)

#: Subset of :data:`WINGS_AFFECTING_FIELDS` whose new value only takes effect
#: after the wings process is restarted. ``upload_size`` is hot-applied by
#: wings (it re-reads the limit on every upload), so it's intentionally
#: excluded.
RUNTIME_RESTART_REQUIRED_FIELDS: frozenset[str] = frozenset({
    "scheme",
    "behind_proxy",
    "daemon_listen",
    "daemon_sftp",
    "daemon_base",
})

#: Fields stored only in ``panel.nodes`` (panel-side scheduling / metadata).
PANEL_ONLY_FIELDS: tuple[str, ...] = (
    "name",
    "description",
    "fqdn",
    "memory",
    "memory_overallocate",
    "disk",
    "disk_overallocate",
    "maintenance_mode",
)

#: All white-listed editable fields.
WHITE_LIST: tuple[str, ...] = WINGS_AFFECTING_FIELDS + PANEL_ONLY_FIELDS


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


def _panel_snapshot(node: PanelNode) -> dict[str, Any]:
    """Extract the white-list fields from a ``PanelNode`` row."""
    return {field: getattr(node, field) for field in WHITE_LIST}


def restart_required_for(changed_fields: Iterable[str]) -> list[str]:
    """Return the subset of ``changed_fields`` that need a wings restart.

    Public helper so the PUT route can report it without re-importing the
    constant directly.
    """
    return sorted(set(changed_fields) & RUNTIME_RESTART_REQUIRED_FIELDS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_state(db: AsyncSession, node: PanelNode) -> dict[str, Any]:
    """Return the node-config snapshot for the admin UI.

    Shape::

        {
            "panel": { …white-listed fields… },
            "wings_service": { active_state, since, … } | None,
            "wings_service_error": str | None,
            "runtime_restart_required_fields": [ …field names… ],
        }

    ``wings_service`` is best-effort: ``None`` (with ``wings_service_error``
    populated) when the agent isn't configured or is unreachable. The UI uses
    ``wings_service.since`` to render "wings last started at ..." so the
    operator can correlate it with their most recent edit and decide whether
    to click "restart wings".

    ``runtime_restart_required_fields`` is the static set of fields whose
    new value only takes effect after wings restarts — the UI shows a banner
    when any of these have unsaved/unrestarted changes.

    NOTE: This endpoint intentionally does **not** probe the wings YAML on
    disk to compute a "drift" set (see module docstring for the rationale).
    For ad-hoc diagnostic comparisons, use ``GET /admin/nodes/{id}/agent/wings-config``.
    """
    panel = _panel_snapshot(node)
    wings_service_state: dict[str, Any] | None = None
    wings_service_error: str | None = None
    try:
        endpoint, token = await host_registry.get_credentials_for_node(
            db, node.id,
        )
        wings_service_state = await agent_client.get_wings_service(
            endpoint, token, timeout=5.0,
        )
    except host_registry.AgentNotConfigured:
        wings_service_error = "agent_not_configured"
    except agent_client.AgentClientError as exc:
        wings_service_error = str(exc)

    return {
        "panel": panel,
        "wings_service": wings_service_state,
        "wings_service_error": wings_service_error,
        "runtime_restart_required_fields": sorted(RUNTIME_RESTART_REQUIRED_FIELDS),
    }


def _build_wings_payload(node: PanelNode, changed_fields: Iterable[str]) -> dict[str, Any] | None:
    """Build a partial Configuration JSON for ``POST /api/update``.

    Only emits sub-trees that contain fields wings actually consumes among
    ``changed_fields``. Returns ``None`` when no wings-affecting field was
    modified (the caller should skip the wings push entirely).

    The payload always carries ``token`` + ``token_id`` (matches Pterodactyl
    panel behaviour: every push refreshes the daemon credentials so that token
    rotation is automatically applied).

    Mapping mirrors Pterodactyl panel ``Node::getConfiguration()`` —
    see also ``docs/MONITORING_AND_AGENT.md`` §11.1.
    """
    affecting = set(changed_fields) & set(WINGS_AFFECTING_FIELDS)
    if not affecting:
        return None

    payload: dict[str, Any] = {
        "token_id": node.daemon_token_id,
        "token": wings_service._decrypt_laravel(node.daemon_token),
    }

    api_block: dict[str, Any] = {}
    if "daemon_listen" in affecting:
        api_block["port"] = node.daemon_listen
    if "upload_size" in affecting:
        api_block["upload_limit"] = node.upload_size
    # ssl.enabled is derived from (scheme, behind_proxy). NEVER touch
    # ``ssl.cert`` / ``ssl.key`` paths here — those are owned by the cert
    # deployment pipeline (PR-E). Overwriting them on every fqdn/scheme
    # change would silently clobber operator-customised paths and break
    # wings on the next restart. Wings preserves the existing values when
    # the keys are omitted from the JSON patch (Gin BindJSON behaviour).
    if "scheme" in affecting or "behind_proxy" in affecting:
        ssl_enabled = node.scheme == "https" and not node.behind_proxy
        api_block["ssl"] = {"enabled": ssl_enabled}
    if api_block:
        payload["api"] = api_block

    system_block: dict[str, Any] = {}
    if "daemon_base" in affecting:
        system_block["data"] = node.daemon_base
    if "daemon_sftp" in affecting:
        system_block["sftp"] = {"bind_port": node.daemon_sftp}
    if system_block:
        payload["system"] = system_block

    return payload


async def push_to_wings(
    db: AsyncSession,
    node: PanelNode,
    changed_fields: Iterable[str],
    *,
    override_base_url: str | None = None,
    override_token: str | None = None,
) -> dict[str, Any]:
    """Push the wings-affecting subset to ``POST /api/update``.

    Returns ``{"pushed": False, "reason": "..."}`` when no wings-affecting
    field changed, otherwise ``{"pushed": True, "applied": bool, "fields": [...]}``.
    Raises :class:`WingsServiceError` on transport or auth failure.

    ``override_base_url`` / ``override_token`` let the caller target the wings
    endpoint that was reachable **before** the panel mutation — needed when
    the change itself rotates ``fqdn`` / ``scheme`` / ``daemon_listen`` /
    daemon token.
    """
    payload = _build_wings_payload(node, changed_fields)
    if payload is None:
        return {"pushed": False, "reason": "no_wings_affecting_field"}

    response = await wings_service.post_node_update(
        db,
        node.id,
        payload,
        explicit_token=override_token,
        explicit_base_url=override_base_url,
    )
    return {
        "pushed": True,
        "applied": bool(response.get("applied", True)),
        "fields": sorted(set(changed_fields) & set(WINGS_AFFECTING_FIELDS)),
    }


# ---------------------------------------------------------------------------
# Daemon token rotation
# ---------------------------------------------------------------------------

#: Length of the random ``token_id`` (matches Pterodactyl panel behaviour).
_TOKEN_ID_LEN = 16
#: Length of the random ``token`` (matches Pterodactyl panel behaviour).
_TOKEN_LEN = 64


def _generate_token() -> tuple[str, str]:
    """Return ``(token_id, token)`` matching panel's character pool.

    Pterodactyl panel uses ``Str::random(16)`` / ``Str::random(64)`` which
    draws from ``[A-Za-z0-9]``. We use :func:`secrets.choice` over the same
    alphabet so the format is byte-for-byte interchangeable.
    """
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    return (
        "".join(secrets.choice(alphabet) for _ in range(_TOKEN_ID_LEN)),
        "".join(secrets.choice(alphabet) for _ in range(_TOKEN_LEN)),
    )


async def reset_daemon_token(
    db: AsyncSession,
    node: PanelNode,
) -> dict[str, Any]:
    """Rotate the wings daemon master key.

    Sequence (panel-equivalent ``NodeUpdateService::resetToken``):

    1. Generate fresh ``token_id`` + ``token``.
    2. Push to wings ``POST /api/update`` **using the old token to authenticate**
       while the JSON body carries the new credentials. This avoids a chicken-
       and-egg situation where wings would reject manager's new-token request
       before it had switched.
    3. Only when wings accepts the push do we persist the new credentials to
       ``panel.nodes`` and clear the cached node info.

    Failure semantics: a wings push failure raises :class:`WingsServiceError`
    *without* having mutated ``panel.nodes`` (no rollback necessary).

    Returns ``{"applied": bool, "token_id": new_id}``.
    """
    new_token_id, new_token_plain = _generate_token()
    old_token_plain = wings_service._decrypt_laravel(node.daemon_token)

    payload: dict[str, Any] = {
        "token_id": new_token_id,
        "token": new_token_plain,
    }
    response = await wings_service.post_node_update(
        db,
        node.id,
        payload,
        explicit_token=old_token_plain,
    )

    applied = bool(response.get("applied", True))
    if not applied:
        # Wings has ``ignore_panel_config_updates: true`` — it accepted the
        # HTTP request but refused to swap the token in-process. Persisting
        # the new credentials would silently desync manager from wings: the
        # next call would 401 and the only recovery is SSH. Refuse loudly
        # instead and leave panel.nodes untouched.
        raise WingsServiceError(
            "wings refused to apply the new daemon token "
            "(ignore_panel_config_updates is enabled on this node); "
            "panel credentials left untouched"
        )

    # Wings accepted the new credentials — now make panel.nodes match.
    node.daemon_token_id = new_token_id
    node.daemon_token = wings_service._encrypt_laravel(new_token_plain)
    await db.commit()
    await db.refresh(node)
    wings_service.clear_cache()

    return {
        "applied": True,
        "token_id": new_token_id,
    }
