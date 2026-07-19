"""Pydantic schemas for the user-agreement system.

See ``docs/USER_AGREEMENT_DESIGN.md`` §4 for the schema contract.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AcceptanceItem(BaseModel):
    """One checkbox on the consent form: agreement id + the version the
    user claims to have read.

    The server re-validates ``version`` against ``agreement.current_version``
    in :func:`app.services.agreements.validate_acceptance`; a stale or
    tampered value is rejected with 400.
    """

    agreement_id: int
    version: int


class AgreementPublicOut(BaseModel):
    """Public (no-auth) read model for a single agreement's current version.

    The ``title`` / ``body_md`` fields are pre-resolved by the service
    layer according to the requested locale, with fallback to the other
    language when the requested one is missing. ``agreement_id`` is
    included so the registration / purchase form can build the
    ``[{agreement_id, version}]`` payload directly (the server's
    ``validate_acceptance`` resolves by id).
    """

    agreement_id: int
    slug: str
    scope: str
    version: int
    title: str
    body_md: str


class AgreementAdminOut(BaseModel):
    """Admin read model for an agreement definition, including the current
    version pointer and version count (for the management list view).
    """

    id: int
    slug: str
    scope: str
    egg_id: int | None = None
    require_register: bool
    require_purchase: bool
    is_enabled: bool
    sort_order: int
    current_version: int
    version_count: int = 0
    current_title_zh: str = ""
    current_title_en: str = ""
    created_at: str
    updated_at: str


class AgreementUpsert(BaseModel):
    """Create / update payload for an agreement definition.

    ``slug`` is immutable after creation (it's the public URL key).
    """

    slug: str = Field(min_length=1, max_length=32)
    scope: str = Field(default="global", max_length=16)
    egg_id: int | None = None
    require_register: bool = False
    require_purchase: bool = False
    is_enabled: bool = True
    sort_order: int = 0


class PublishVersionRequest(BaseModel):
    """Publish a new version body for an agreement.

    * ``bump=True``  → insert a new ``AgreementVersion`` row with
      ``version = max+1`` and advance ``current_version``; this triggers
      re-consent for every existing user.
    * ``bump=False`` → overwrite the current version's body in place;
      no version bump, no re-consent. Only allowed when a current
      version already exists (``current_version > 0``).
    """

    title_zh: str = Field(default="", max_length=191)
    title_en: str = Field(default="", max_length=191)
    body_zh: str = ""
    body_en: str = ""
    bump: bool = True


class AgreementVersionOut(BaseModel):
    """Admin read model for one version row."""

    id: int
    version: int
    title_zh: str
    title_en: str
    body_zh: str
    body_en: str
    published_at: str
    published_by: str
