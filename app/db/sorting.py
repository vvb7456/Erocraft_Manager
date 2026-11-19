"""Shared SQLAlchemy ORDER BY builder with whitelist mapping and NULLS LAST."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import case, or_


@dataclass(frozen=True, slots=True)
class SortSpec:
    column: Any
    nulls_last: bool = False
    empty_as_null: bool = False
    tie_breakers: tuple[Any, ...] | None = None


def build_order_by(
    sort_by: str | None,
    sort_order: str,
    columns: Mapping[str, Any | SortSpec],
    *,
    default: Sequence[Any],
    tie_breakers: Sequence[Any] = (),
) -> tuple[Any, ...]:
    if not sort_by or sort_by not in columns:
        return tuple(default)

    raw_spec = columns[sort_by]
    spec = raw_spec if isinstance(raw_spec, SortSpec) else SortSpec(raw_spec)
    is_asc = sort_order == "asc"

    clauses: list[Any] = []
    if spec.nulls_last:
        null_cond = (
            or_(spec.column.is_(None), spec.column == "")
            if spec.empty_as_null
            else spec.column.is_(None)
        )
        clauses.append(case((null_cond, 1), else_=0).asc())

    clauses.append(spec.column.asc() if is_asc else spec.column.desc())

    ties = spec.tie_breakers if spec.tie_breakers is not None else tie_breakers
    for tie in ties:
        if tie is spec.column:
            continue
        clauses.append(tie.asc() if is_asc else tie.desc())

    return tuple(clauses)
