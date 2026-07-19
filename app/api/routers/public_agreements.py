"""Public (no-auth) agreement read endpoints.

Used by the registration form and the standalone ``/agreement/:slug``
page. All endpoints are GET and read-only — they surface the *current*
version body only; historical versions are admin-only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.db import get_db
from app.schemas.agreements import AgreementPublicOut
from app.services import agreements as agreements_svc

router = APIRouter(tags=["public"])


def _normalize_locale(value: str | None) -> str:
    """Normalize the locale query param to 'zh-CN' / 'en'.

    The frontend uses 'zh-CN' and 'en'; accepting the bare two-letter
    codes too avoids surprises if someone hits the API directly.
    """
    v = (value or "").strip().lower()
    if v.startswith("zh"):
        return "zh-CN"
    if v.startswith("en"):
        return "en"
    return "zh-CN"


@router.get(
    "/public/agreements",
    response_model=list[AgreementPublicOut],
)
async def list_public_agreements(
    context: str = Query(default="register"),
    egg_id: int | None = Query(default=None),
    locale: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[AgreementPublicOut]:
    """List required agreements for a given context, resolved to the
    requested locale.

    ``context`` must be ``register`` or ``purchase``. ``egg_id`` is only
    meaningful with ``context=purchase``. Returns the current version
    body for each agreement the caller must consent to.
    """
    if context not in ("register", "purchase"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="agreements.invalid_context",
        )
    norm = _normalize_locale(locale)
    items = await agreements_svc.list_required(
        db, context=context, egg_id=egg_id
    )
    out: list[AgreementPublicOut] = []
    for agr in items:
        out.append(await agreements_svc.serialize_public(db, agr, norm))
    return out


@router.get(
    "/public/agreements/{slug}",
    response_model=AgreementPublicOut,
)
async def get_public_agreement(
    slug: str,
    locale: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> AgreementPublicOut:
    """Fetch the current version body of a single agreement by slug.

    Returns 404 when the slug doesn't exist, is disabled, or has no
    published version (``current_version == 0``).
    """
    norm = _normalize_locale(locale)
    out = await agreements_svc.public_view(db, slug, norm)
    if out is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="agreements.not_found"
        )
    return out
