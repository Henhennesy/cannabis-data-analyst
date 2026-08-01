"""get_brand_share -- brands ranked within a segment, with share of that segment.

The share denominator is the WHOLE segment, not the returned rows. A window
function computes it before LIMIT is applied, so asking for the top 20 gives
each brand's share of the full segment rather than its share of the top 20 --
which would be a different, and wrong, number.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import cache
from ..dataset import KNOWN_PARTIAL_YEARS, available_years, caveats_for, data_fingerprint
from ..db import run_query
from ..envelope import Coverage, ToolEnvelope
from ..schema_registry import METRICS, MV_BRAND, RELATIONS, metric_column
from .filters import validate_dimensions

TOOL_NAME = "get_brand_share"

MAX_TOP_N = 200

ANTHROPIC_TOOL = {
    "name": TOOL_NAME,
    "description": (
        "Brands ranked within a category segment for one year, with each brand's "
        "absolute value and its percent of the whole segment. Use for 'who leads', "
        "'top brands in', and share-of-segment questions. "
        "category_l2 is the segment (e.g. 'Edibles', 'Vape', 'Flower') -- confirm the "
        "value with list_dimension_values first. Percentages are share of the FULL "
        "segment, not of the returned rows."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "category_l2": {
                "type": "string",
                "description": "The segment, e.g. 'Edibles'. Note edibles sit under category_l1='Ingestibles'.",
            },
            "period": {
                "type": "integer",
                "description": "The year. Data is annual; there is no month or quarter grain.",
            },
            "metric": {"type": "string", "enum": sorted(METRICS)},
            "states": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional state restriction. Omit for all covered states.",
            },
            "top_n": {
                "type": "integer",
                "default": 20,
                "description": f"How many brands to return, max {MAX_TOP_N}.",
            },
        },
        "required": ["category_l2", "period", "metric"],
        "additionalProperties": False,
    },
}


class GetBrandShareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_l2: str
    period: int
    metric: str
    states: list[str] = Field(default_factory=list)
    top_n: int = Field(default=20, ge=1, le=MAX_TOP_N)

    @field_validator("metric")
    @classmethod
    def _known_metric(cls, v: str) -> str:
        if v not in METRICS:
            raise ValueError(f"unknown metric {v!r}; expected one of {sorted(METRICS)}")
        return v


def get_brand_share(inp: GetBrandShareInput) -> ToolEnvelope:
    key = inp.model_dump()
    version = data_fingerprint()
    cached = cache.get(TOOL_NAME, key, version.fingerprint)
    if cached is not None:
        return ToolEnvelope.model_validate(cached)

    loaded = available_years()
    if inp.period not in loaded:
        return ToolEnvelope.failed(
            f"No data for {inp.period}. The database contains only "
            f"{', '.join(str(y) for y in loaded)}.",
            params=key,
        )

    validate_dimensions(["category_l2"])
    relation = RELATIONS[MV_BRAND]
    measure = metric_column(relation.name, inp.metric)

    where_parts = [
        sql.SQL("category_l2 = %(seg)s"),
        sql.SQL("period_year = %(yr)s"),
    ]
    params: dict[str, Any] = {"seg": inp.category_l2, "yr": inp.period, "n": inp.top_n}
    if inp.states:
        where_parts.append(sql.SQL("state = ANY(%(states)s)"))
        params["states"] = sorted(inp.states)

    # sum(sum(x)) OVER () is the segment total. Window functions are evaluated
    # before LIMIT, so this stays the full-segment denominator no matter what
    # top_n is.
    query = sql.SQL(
        "SELECT brand, "
        "sum({m}) AS {metric_name}, "
        "sum({m}) / NULLIF(sum(sum({m})) OVER (), 0) AS share_of_segment, "
        "sum(sku_rows) AS sku_rows "
        "FROM public.{rel} WHERE {where} "
        "GROUP BY brand ORDER BY 2 DESC NULLS LAST LIMIT %(n)s"
    ).format(
        m=sql.Identifier(measure),
        metric_name=sql.Identifier(inp.metric),
        rel=sql.Identifier(relation.name),
        where=sql.SQL(" AND ").join(where_parts),
    )

    try:
        result = run_query(query, params)
    except psycopg.errors.QueryCanceled:
        return ToolEnvelope.failed(
            f"The query exceeded the statement timeout ranking brands in "
            f"{inp.category_l2!r}.",
            params=key,
        )

    rows = [
        {
            "brand": r["brand"],
            inp.metric: float(r[inp.metric]) if r[inp.metric] is not None else None,
            "share_of_segment": float(r["share_of_segment"])
            if r["share_of_segment"] is not None else None,
            "percent_of_segment": round(float(r["share_of_segment"]) * 100, 4)
            if r["share_of_segment"] is not None else None,
            "sku_rows": r["sku_rows"],
        }
        for r in result.rows
    ]

    if not rows:
        return ToolEnvelope.failed(
            f"No rows for category_l2={inp.category_l2!r} in {inp.period}. Confirm the "
            f"segment name with list_dimension_values(dimension='category_l2') -- note "
            f"that edibles are category_l2='Edibles' under category_l1='Ingestibles', "
            f"and the inhalation category is spelled 'Inhaleables'.",
            sql_text=result.sql,
            params=key,
        )

    covered_share = sum(r["share_of_segment"] or 0.0 for r in rows)
    states = inp.states or _states_in_scope(relation.name, params, where_parts)
    partial = [inp.period] if inp.period in KNOWN_PARTIAL_YEARS else []

    notes = [
        "BDSA is retail sell-through in covered states only. It is not total market.",
        f"Percentages are share of the FULL {inp.category_l2} segment, not of the "
        f"{len(rows)} brands returned.",
        f"These {len(rows)} brands account for {covered_share * 100:.1f}% of the "
        f"segment; the remainder is spread across brands outside the top {inp.top_n}.",
        f"Metric is {inp.metric}. Brand rank by dollars and by units can differ.",
        f"From {relation.name}, which excludes suppressed rows.",
    ]
    if partial:
        notes.append(
            f"{inp.period} is a partial year of unknown, state-varying width. Brand "
            f"SHARES remain meaningful because the window cancels between a brand and "
            f"its segment, but the absolute values are not a full-year figure and "
            f"should not be compared across states or to another year."
        )

    envelope = ToolEnvelope(
        rows=rows,
        row_count=len(rows),
        sql=result.sql,
        params=key,
        coverage=Coverage(
            period_start=inp.period,
            period_end=inp.period,
            states=states,
            partial_periods=partial,
            caveats=caveats_for([inp.period]),
        ),
        truncated=len(rows) >= inp.top_n,
        relation=relation.name,
        notes=notes,
    )
    cache.put(TOOL_NAME, key, version.fingerprint, envelope.model_dump())
    return envelope


def _states_in_scope(relation: str, params: dict, where_parts: list) -> list[str]:
    q = sql.SQL("SELECT DISTINCT state FROM public.{rel} WHERE {where} ORDER BY 1").format(
        rel=sql.Identifier(relation), where=sql.SQL(" AND ").join(where_parts)
    )
    try:
        return [r["state"] for r in run_query(q, params).rows]
    except psycopg.errors.QueryCanceled:
        return []
