"""list_dimension_values -- the primary defence against hallucinated filters.

The agent calls this before using any filter value it has not already
confirmed in the conversation. It is what stops a query for
`category_l1 = 'Edibles'` (which matches nothing) or the plausible-looking
misspelling `Inhalables`.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import cache
from ..config import MAX_ROWS
from ..dataset import caveats_for, data_fingerprint
from ..db import run_query, safe_identifier
from ..envelope import Coverage, ToolEnvelope
from ..schema_registry import ALL_DIMENSIONS, REQUIRES_NARROWING, choose_relation

TOOL_NAME = "list_dimension_values"

ANTHROPIC_TOOL = {
    "name": TOOL_NAME,
    "description": (
        "Returns the distinct values that actually exist for a dimension, with the "
        "dollar sales attached to each. Optionally restricted by other dimensions, so "
        "you can ask what category_l2 values exist under category_l1='Ingestibles'. "
        "ALWAYS call this before filtering on a value you have not already confirmed "
        "in this conversation -- guessed filter values silently return nothing or the "
        "wrong subset."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "dimension": {
                "type": "string",
                "description": "The dimension whose values you want.",
                "enum": sorted(ALL_DIMENSIONS),
            },
            "filter_by": {
                "type": "object",
                "description": (
                    "Optional restriction, e.g. {\"category_l1\": \"Ingestibles\"}. "
                    "Values must be exact; call this tool on the filter dimension "
                    "first if unsure."
                ),
                "additionalProperties": {"type": ["string", "number", "boolean"]},
            },
        },
        "required": ["dimension"],
        "additionalProperties": False,
    },
}


class ListDimensionValuesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str
    filter_by: dict[str, Any] = Field(default_factory=dict)

    @field_validator("dimension")
    @classmethod
    def _known_dimension(cls, v: str) -> str:
        safe_identifier(v)
        if v not in ALL_DIMENSIONS:
            raise ValueError(
                f"unknown dimension {v!r}. Valid dimensions: {sorted(ALL_DIMENSIONS)}"
            )
        return v

    @field_validator("filter_by")
    @classmethod
    def _known_filters(cls, v: dict[str, Any]) -> dict[str, Any]:
        for key in v:
            safe_identifier(key)
            if key not in ALL_DIMENSIONS:
                raise ValueError(
                    f"unknown filter dimension {key!r}. "
                    f"Valid dimensions: {sorted(ALL_DIMENSIONS)}"
                )
        return v


def list_dimension_values(inp: ListDimensionValuesInput) -> ToolEnvelope:
    params_key = {"dimension": inp.dimension, "filter_by": inp.filter_by}
    version = data_fingerprint()

    cached = cache.get(TOOL_NAME, params_key, version.fingerprint)
    if cached is not None:
        return ToolEnvelope.model_validate(cached)

    if inp.dimension in REQUIRES_NARROWING and not inp.filter_by:
        return ToolEnvelope.failed(
            f"{inp.dimension!r} has too many distinct values to list without "
            f"narrowing (over 3 million, which would exceed both the {MAX_ROWS}-row "
            f"limit and the statement timeout). Supply filter_by with at least one "
            f"other dimension, for example "
            f"{{'category_l1': 'Ingestibles', 'category_l2': 'Edibles'}}.",
            params={"dimension": inp.dimension},
        )

    needed = {inp.dimension, *inp.filter_by, "period_year", "state"}
    relation = choose_relation(needed)

    where_parts: list[sql.Composed] = []
    params: dict[str, Any] = {}
    for i, (col, value) in enumerate(sorted(inp.filter_by.items())):
        key = f"f{i}"
        where_parts.append(
            sql.SQL("{} = %({})s").format(sql.Identifier(col), sql.SQL(key))
        )
        params[key] = value

    where = (
        sql.SQL(" WHERE ") + sql.SQL(" AND ").join(where_parts)
        if where_parts else sql.SQL("")
    )

    query = sql.SQL(
        "SELECT {dim} AS value, "
        "count(*) AS row_count, "
        "sum({dollars}) AS dollar_sales, "
        "min(period_year) AS first_year, "
        "max(period_year) AS last_year "
        "FROM public.{rel}{where} "
        "GROUP BY 1 ORDER BY dollar_sales DESC NULLS LAST, 1"
    ).format(
        dim=sql.Identifier(inp.dimension),
        dollars=sql.Identifier(relation.dollars),
        rel=sql.Identifier(relation.name),
        where=where,
    )

    try:
        result = run_query(query, params, max_rows=MAX_ROWS)
    except psycopg.errors.QueryCanceled:
        # Never let a timeout look like an empty result. The agent must report
        # that the query failed, not that the answer is zero.
        return ToolEnvelope.failed(
            f"The query exceeded the statement timeout while listing "
            f"{inp.dimension!r} from {relation.name}. Narrow it with filter_by "
            f"and try again.",
            params={"dimension": inp.dimension, **inp.filter_by},
        )

    rows = [
        {
            "value": r["value"],
            "row_count": r["row_count"],
            "dollar_sales": float(r["dollar_sales"]) if r["dollar_sales"] is not None else None,
            "first_year": r["first_year"],
            "last_year": r["last_year"],
        }
        for r in result.rows
    ]

    years = sorted({y for r in result.rows for y in (r["first_year"], r["last_year"]) if y})
    states = _states_for(relation.name, inp.filter_by, params)

    notes: list[str] = []
    if relation.excludes_suppressed:
        notes.append(
            f"Counted from {relation.name}, which excludes suppressed rows. "
            "Values appearing only on suppressed rows are not listed."
        )
    if result.truncated:
        notes.append(
            f"Truncated at {MAX_ROWS} values; this dimension has more. "
            "Narrow with filter_by."
        )
    if not rows:
        notes.append(
            "No values matched. The filter values may not exist -- call this tool "
            "on the filter dimension to see what does."
        )

    envelope = ToolEnvelope(
        rows=rows,
        row_count=len(rows),
        sql=result.sql,
        params={"dimension": inp.dimension, **inp.filter_by},
        coverage=Coverage(
            period_start=years[0] if years else None,
            period_end=years[-1] if years else None,
            states=states,
            partial_periods=[y for y in years if y in (2026,)],
            caveats=caveats_for(years),
        ),
        truncated=result.truncated,
        relation=relation.name,
        notes=notes,
    )
    cache.put(TOOL_NAME, params_key, version.fingerprint, envelope.model_dump())
    return envelope


def _states_for(relation: str, filter_by: dict[str, Any], _params: dict) -> list[str]:
    """State set the listing applies to, so the envelope carries its scope."""
    if "state" in filter_by:
        return [str(filter_by["state"])]
    where_parts: list[sql.Composed] = []
    params: dict[str, Any] = {}
    for i, (col, value) in enumerate(sorted(filter_by.items())):
        key = f"f{i}"
        where_parts.append(sql.SQL("{} = %({})s").format(sql.Identifier(col), sql.SQL(key)))
        params[key] = value
    where = (
        sql.SQL(" WHERE ") + sql.SQL(" AND ").join(where_parts)
        if where_parts else sql.SQL("")
    )
    q = sql.SQL("SELECT DISTINCT state FROM public.{rel}{where} ORDER BY 1").format(
        rel=sql.Identifier(relation), where=where
    )
    return [r["state"] for r in run_query(q, params).rows]
