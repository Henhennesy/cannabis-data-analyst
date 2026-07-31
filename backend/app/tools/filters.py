"""Shared WHERE-clause construction.

Both aggregation tools build filters the same way, deliberately: two
implementations would eventually disagree, and a disagreement here is a silently
wrong number rather than an error.

Identifiers are validated against the schema registry and a syntactic
allowlist before they reach SQL. Values are always bound as parameters, never
interpolated.
"""

from __future__ import annotations

from typing import Any

from psycopg import sql

from ..db import safe_identifier
from ..schema_registry import ALL_DIMENSIONS, FACT, Relation

FilterValue = str | int | float | bool | list


def validate_dimensions(names, *, label: str = "dimension") -> None:
    for name in names:
        safe_identifier(name)
        if name not in ALL_DIMENSIONS:
            raise ValueError(
                f"unknown {label} {name!r}. Valid dimensions: {sorted(ALL_DIMENSIONS)}"
            )


def build_where(
    filters: dict[str, FilterValue],
    relation: Relation,
    *,
    include_suppressed: bool = False,
    prefix: str = "f",
    extra: list[sql.Composed] | None = None,
    params: dict[str, Any] | None = None,
) -> tuple[sql.Composed, dict[str, Any]]:
    """Returns (WHERE clause, params). The clause is empty SQL if nothing applies."""
    validate_dimensions(filters)
    params = dict(params or {})
    parts: list[sql.Composed] = list(extra or [])

    for i, (col, value) in enumerate(sorted(filters.items())):
        key = f"{prefix}{i}"
        if isinstance(value, (list, tuple, set)):
            values = sorted(value, key=str)
            if not values:
                raise ValueError(f"filter {col!r} has an empty value list")
            parts.append(
                sql.SQL("{} = ANY(%({})s)").format(sql.Identifier(col), sql.SQL(key))
            )
            params[key] = list(values)
        else:
            parts.append(
                sql.SQL("{} = %({})s").format(sql.Identifier(col), sql.SQL(key))
            )
            params[key] = value

    # The materialized views are built WHERE NOT is_suppressed, so a fact-table
    # query must exclude suppressed rows too or the two paths return different
    # totals for the same question.
    if relation.name == FACT and not include_suppressed:
        parts.append(sql.SQL("NOT is_suppressed"))

    if not parts:
        return sql.SQL(""), params
    return sql.SQL(" WHERE ") + sql.SQL(" AND ").join(parts), params


def year_predicate(start: int, end: int, key_start: str = "y0", key_end: str = "y1"):
    return sql.SQL("period_year BETWEEN %({})s AND %({})s").format(
        sql.SQL(key_start), sql.SQL(key_end)
    )


def merge_numerator_filters(
    denominator: dict[str, FilterValue], numerator: dict[str, FilterValue]
) -> dict[str, FilterValue]:
    """The numerator is always a REFINEMENT of the denominator.

    Defined once, here, so the model never reinvents the arithmetic. If the
    numerator were evaluated independently it could select rows outside the
    denominator entirely and produce a ratio above 1 -- e.g. 'Fast Acting'
    across all categories over a denominator of edibles only.

    A key present in both with a different value is a contradiction, not a
    refinement, and is rejected rather than silently resolved.
    """
    merged = dict(denominator)
    for key, value in numerator.items():
        if key in merged and merged[key] != value:
            raise ValueError(
                f"numerator filter {key}={value!r} contradicts denominator "
                f"{key}={merged[key]!r}. The numerator must be a subset of the "
                f"denominator, not a different population."
            )
        merged[key] = value
    return merged
