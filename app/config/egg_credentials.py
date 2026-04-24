"""Per-egg required-credential variables.

The frontend's startup-credentials confirm dialog talks about "username/password"
specifically — so the backend power-on guard must mirror that scope and only
reject when *credential* variables are empty, not every blank startup variable.

Mapping is keyed by Pterodactyl egg name (case-sensitive, exact match) and
holds the list of env-variable keys whose effective value (user value, falling
back to egg default) must be non-empty before `start` / `restart` is allowed.

Add new eggs here as their own credential rules emerge; eggs not listed here
have no extra constraint beyond what Pterodactyl itself enforces.
"""

from __future__ import annotations

# Egg name -> list of envVariable keys that must have a non-empty value.
EGG_REQUIRED_CREDENTIALS: dict[str, tuple[str, ...]] = {
    "SillyTavern": ("USERNAME", "PASSWORD"),
}


def required_credential_vars(egg_name: str | None) -> tuple[str, ...]:
    """Return the credential env-var keys for an egg, or () if none."""
    if not egg_name:
        return ()
    return EGG_REQUIRED_CREDENTIALS.get(egg_name, ())
