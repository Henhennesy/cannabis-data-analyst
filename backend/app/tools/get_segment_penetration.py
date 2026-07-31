"""get_segment_penetration -- numerator, denominator, and the ratio between them.

The arithmetic is defined once, here, so the model never reinvents it. This is
how "fast-acting share of the edibles market" is computed, and the two ways to
get it wrong are both prevented structurally:

  * The numerator is always a REFINEMENT of the denominator -- the denominator's
    filters are applied to it too. Evaluated independently, a numerator of
    fast_acting='Fast Acting' against a denominator of edibles would be
    selecting from different populations.
  * `fast_acting` is NULL on ~96% of the table. A denominator that forgets to
    restrict to edibles pulls in millions of null-attribute rows and produces a
    share that is far too small while looking perfectly reasonable.

Ratios survive the 2026 partial-year problem: an unknown window cancels between
numerator and denominator as long as both are drawn from the same rows. That is
why this tool stays useful for 2026 when get_market_size does not.
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
from ..schema_registry import ALL_DIMENSIONS, METRICS, choose_relation, metric_column
from .filters import build_where, merge_numerator_filters, validate_dimensions

TOOL_NAME = "get_segment_penetration"

ANTHROPIC_TOOL = {
    "name": TOOL_NAME,
    "description": (
        "Share of one segment within another: returns the numerator, the denominator "
        "and the ratio. Use this for any 'what share / what percent of' question, for "
        "example the fast-acting share of the edibles market. "
        "denominator_filters defines the population (e.g. category_l1='Ingestibles', "
        "category_l2='Edibles'); numerator_filters narrows it further (e.g. "
        "fast_acting='Fast Acting'). The denominator's filters are automatically "
        "applied to the numerator, so do not repeat them. Never compute a share by "
        "dividing two separate get_market_size calls."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "numerator_filters": {
                "type": "object",
                "description": "Additional filters narrowing the denominator population.",
                "additionalProperties": True,
            },
            "denominator_filters": {
                "type": "object",
                "description": "Filters defining the population being divided into.",
                "additionalProperties": True,
            },
            "period": {
                "type": "integer",
                "description": "The year. Data is annual; there is no month or quarter grain.",
            },
            "states": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional state restriction. Omit for all covered states.",
            },
            "metric": {"type": "string", "enum": sorted(METRICS)},
            "include_suppressed": {"type": "boolean", "default": False},
        },
        "required": ["numerator_filters", "denominator_filters", "period", "metric"],
        "additionalProperties": False,
    },
}


class GetSegmentPenetrationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numerator_filters: dict[str, Any]
    denominator_filters: dict[str, Any]
    period: int
    metric: str
    states: list[str] = Field(default_factory=list)
    include_suppressed: bool = False

    @field_validator("metric")
    @classmethod
    def _known_metric(cls, v: str) -> str:
        if v not in METRICS:
            raise ValueError(f"unknown metric {v!r}; expected one of {sorted(METRICS)}")
        return v

    @field_validator("numerator_filters", "denominator_filters")
    @classmethod
    def _known_filters(cls, v: dict) -> dict:
        validate_dimensions(v, label="filter dimension")
        return v


def get_segment_penetration(inp: GetSegmentPenetrationInput) -> ToolEnvelope:
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

    if not inp.denominator_filters:
        return ToolEnvelope.failed(
            "denominator_filters is empty, which would make the denominator the "
            "entire market. State the population explicitly, e.g. "
            "{'category_l1': 'Ingestibles', 'category_l2': 'Edibles'}.",
            params=key,
        )

    try:
        numerator_filters = merge_numerator_filters(
            inp.denominator_filters, inp.numerator_filters
        )
    except ValueError as exc:
        return ToolEnvelope.failed(str(exc), params=key)

    base_filters = dict(inp.denominator_filters)
    if inp.states:
        base_filters["state"] = inp.states
        numerator_filters["state"] = inp.states

    needed = set(numerator_filters) | {"period_year"}
    relation = choose_relation(needed, require_fact=inp.include_suppressed)
    measure = metric_column(relation.name, inp.metric)

    # One pass over one population. The numerator is a FILTER on the same
    # aggregate, not a second query, so the two can never be drawn from
    # different row sets.
    num_parts: list[sql.Composed] = []
    params: dict[str, Any] = {"yr": inp.period}
    for i, (col, value) in enumerate(sorted(inp.numerator_filters.items())):
        k = f"n{i}"
        if isinstance(value, (list, tuple, set)):
            num_parts.append(
                sql.SQL("{} = ANY(%({})s)").format(sql.Identifier(col), sql.SQL(k))
            )
            params[k] = sorted(value, key=str)
        else:
            num_parts.append(
                sql.SQL("{} = %({})s").format(sql.Identifier(col), sql.SQL(k))
            )
            params[k] = value
    num_predicate = sql.SQL(" AND ").join(num_parts) if num_parts else sql.SQL("TRUE")

    where, params = build_where(
        base_filters,
        relation,
        include_suppressed=inp.include_suppressed,
        extra=[sql.SQL("period_year = %(yr)s")],
        params=params,
    )

    query = sql.SQL(
        "SELECT sum({m}) FILTER (WHERE {num}) AS numerator, "
        "sum({m}) AS denominator, "
        "count(*) FILTER (WHERE {num}) AS numerator_rows, "
        "count(*) AS denominator_rows, "
        "count(DISTINCT state) AS state_count "
        "FROM public.{rel}{where}"
    ).format(
        m=sql.Identifier(measure),
        num=num_predicate,
        rel=sql.Identifier(relation.name),
        where=where,
    )

    try:
        result = run_query(query, params)
    except psycopg.errors.QueryCanceled:
        return ToolEnvelope.failed(
            f"The query exceeded the statement timeout against {relation.name}.",
            params=key,
        )

    row = result.rows[0]
    numerator = float(row["numerator"]) if row["numerator"] is not None else 0.0
    denominator = float(row["denominator"]) if row["denominator"] is not None else 0.0

    if row["denominator"] is None or denominator == 0:
        return ToolEnvelope.failed(
            "The denominator population is empty, so no share can be computed. "
            "Verify the denominator filter values with list_dimension_values -- "
            "note that category_l1='Edibles' matches nothing; edibles are "
            "category_l2='Edibles' under category_l1='Ingestibles'.",
            sql_text=result.sql,
            params=key,
        )

    ratio = numerator / denominator
    if ratio > 1.0000001:
        # Structurally impossible given the merge, so if it happens the tool is
        # wrong and must say so rather than emit an absurd share.
        return ToolEnvelope.failed(
            f"Computed a share above 100% ({ratio:.4%}), which means the numerator "
            f"is not a subset of the denominator. Refusing to report it.",
            sql_text=result.sql,
            params=key,
        )

    states = inp.states or _states_in_scope(relation, params, where)
    partial = [inp.period] if inp.period in KNOWN_PARTIAL_YEARS else []

    notes = [
        "BDSA is retail sell-through in covered states only. It is not total market.",
        f"Metric is {inp.metric}. The dollar share and the unit share of the same "
        f"segment differ materially; do not substitute one for the other.",
        "The denominator's filters were applied to the numerator as well, so the "
        "numerator is a strict subset of the denominator.",
    ]
    if relation.excludes_suppressed:
        notes.append(f"From {relation.name}, which excludes suppressed rows.")
    if partial:
        notes.append(
            f"{inp.period} is a partial year, but a RATIO is still valid: the unknown "
            f"window cancels between numerator and denominator because both are drawn "
            f"from the same rows. The absolute values are not a full-year market size."
        )

    envelope = ToolEnvelope(
        rows=[
            {
                "numerator": numerator,
                "denominator": denominator,
                "ratio": ratio,
                "percent": ratio * 100,
                "metric": inp.metric,
                "period": inp.period,
                "numerator_rows": row["numerator_rows"],
                "denominator_rows": row["denominator_rows"],
                "state_count": row["state_count"],
            }
        ],
        row_count=1,
        sql=result.sql,
        params=key,
        coverage=Coverage(
            period_start=inp.period,
            period_end=inp.period,
            states=states,
            partial_periods=partial,
            caveats=caveats_for([inp.period]),
        ),
        truncated=False,
        relation=relation.name,
        notes=notes,
    )
    cache.put(TOOL_NAME, key, version.fingerprint, envelope.model_dump())
    return envelope


def _states_in_scope(relation, params, where) -> list[str]:
    q = sql.SQL("SELECT DISTINCT state FROM public.{rel}{where} ORDER BY 1").format(
        rel=sql.Identifier(relation.name), where=where
    )
    try:
        return [r["state"] for r in run_query(q, params).rows]
    except psycopg.errors.QueryCanceled:
        return []
