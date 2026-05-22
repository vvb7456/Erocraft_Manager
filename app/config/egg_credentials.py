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

import re

# Egg name -> list of envVariable keys that must have a non-empty value.
EGG_REQUIRED_CREDENTIALS: dict[str, tuple[str, ...]] = {
    "SillyTavern": ("USERNAME", "PASSWORD"),
}


def required_credential_vars(egg_name: str | None) -> tuple[str, ...]:
    """Return the credential env-var keys for an egg, or () if none."""
    if not egg_name:
        return ()
    return EGG_REQUIRED_CREDENTIALS.get(egg_name, ())


# --- Per-egg startup variable value validators ---------------------------
#
# Wings writes egg variables into the container's config.yaml via the
# `parser: yaml` mechanism. A purely numeric value like USERNAME=`123456`
# round-trips through go-yaml as an *integer*, and SillyTavern's basic-auth
# middleware compares via strict `===` against the string from the HTTP
# Authorization header — string `"123456"` !== number `123456`, so login
# fails forever. Mirror the frontend check on the backend so direct API
# callers can't bypass it.
_LETTER_RE = re.compile(r"[A-Za-z]")


def validate_startup_variable(egg_name: str | None, env_variable: str, value: str) -> str | None:
    """Return an error message if the value is invalid for this egg+var, else None."""
    if egg_name == "SillyTavern":
        if env_variable == "USERNAME":
            if not value:
                return "USERNAME is required"
            if any(ch.isspace() for ch in value):
                return "USERNAME cannot contain whitespace"
            if ":" in value:
                return "USERNAME cannot contain a colon"
            if not _LETTER_RE.search(value):
                return (
                    "USERNAME must contain at least one letter; purely numeric "
                    "usernames are parsed as integers by YAML and break login"
                )
    return None

