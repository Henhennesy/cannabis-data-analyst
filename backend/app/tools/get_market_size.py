"""get_market_size -- aggregated dollar or unit totals for a filtered slice.

Two refusals are built in, both because the alternative is a number that looks
authoritative and is not:

  * A period outside coverage returns an error, never zero.
  * A range spanning a complete year and a partial one is refused unless the
    results are broken out by year, because summing 2025 and 2026 into a
    single figure silently mixes twelve months with an unknown number.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import cache
from ..config import MAX_ROWS
from ..dataset import KNOWN_PARTIAL_YEARS, available_years, caveats_for, data_fingerprint
from ..db import run_query
from ..envelope import Coverage, ToolEnvelope
from ..schema_registry import ALL_DIMENSIONS, METRICS, choose_relation, metric_column
from .filters import build_where, validate_dimensions, year_predicate

TOOL_NAME = "get_market_size"

ANTHROPIC_TOOL = {
    "name": TOOL_NAME,
    "description": (
        "Total dollar sales or unit sales for a filtered slice of the market, "
        "optionally broken out by one or more dimensions. Use for category and "
        "segment sizing, brand totals, and state-level totals. "
        "'dollar_sales' and 'unit_sales' are different questions -- ask the user "
        "which they mean rather than guessing. Confirm filter values with "
        "list_dimension_values first."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "metric": {"type": "string", "enum": sorted(METRICS)},
            "filters": {
                "type": "object",
                "description": (
                    "Dimension equality filters, e.g. "
                    "{\"category_l1\": \"Ingestibles\", \"category_l2\": \"Edibles\"}. "
                    "A value may be a list to match any of several."
                ),
                "additionalProperties": True,
            },
            "start_period": {
                "type": "integer",
                "description": "First year, inclusive. Data is annual; there is no month or quarter grain.",
            },
            "end_period": {"type": "integer", "description": "Last year, inclusive."},
            "group_by": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(ALL_DIMENSIONS)},
                "description": "Dimensions to break the total out by.",
            },
            "include_suppressed": {"type": "boolean", "default": False},
        },
        "required": ["metric", "start_period", "end_period"],
        "additionalProperties": False,
    },
}


class GetMarketSizeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    start_period: int
    end_period: int
    filters: dict[str, Any] = Field(default_factory=dict)
    group_by: list[str] = Field(default_factory=list)
    include_suppressed: bool = False

    @field_validator("metric")
    @classmethod
    def _known_metric(cls, v: str) -> str:
        if v not in METRICS:
            raise ValueError(f"unknown metric {v!r}; expected one of {sorted(METRICS)}")
        return v

    @field_validator("filters")
    @classmethod
    def _known_filters(cls, v: dict) -> dict:
        validate_dimensions(v, label="filter dimension")
        return v

    @field_validator("group_by")
    @classmethod
    def _known_group_by(cls, v: list[str]) -> list[str]:
        validate_dimensions(v, label="group_by dimension")
        return v


def get_market_size(inp: GetMarketSizeInput) -> ToolEnvelope:
    key = inp.model_dump()
    version = data_fingerprint()
    cached = cache.get(TOOL_NAME, key, version.fingerprint)
    if cached is not None:
        return ToolEnvelope.model_validate(cached)

    if inp.start_period > inp.end_period:
        return ToolEnvelope.failed(
            f"start_period {inp.start_period} is after end_period {inp.end_period}.",
            params=key,
        )

    loaded = available_years()
    requested = list(range(inp.start_period, inp.end_period + 1))
    missing = [y for y in requested if y not in loaded]
    if missing:
        return ToolEnvelope.failed(
            f"No data for {', '.join(str(y) for y in missing)}. "
            f"The database contains only {', '.join(str(y) for y in loaded)}. "
            f"Do not report a figure for a period that is not loaded.",
            params=key,
        )

    covered = [y for y in requested if y in loaded]
    partial = sorted(set(covered) & KNOWN_PARTIAL_YEARS)
    complete = [y for y in covered if y not in KNOWN_PARTIAL_YEARS]

    # Summing a complete year and a partial one into a single figure is the
    # same error as a bare year-over-year comparison, just harder to spot.
    if partial and complete and "period_year" not in inp.group_by:
        return ToolEnvelope.failed(
            f"Refusing to sum {', '.join(str(y) for y in complete)} together with "
            f"{', '.join(str(y) for y in partial)}: the latter is a partial year of "
            f"unknown width, so the combined total is not a meaningful market size. "
            f"Either query a single year, or add 'period_year' to group_by so the "
            f"years are reported separately.",
            params=key,
        )

    needed = set(inp.filters) | set(inp.group_by) | {"period_year"}
    relation = choose_relation(needed, require_fact=inp.include_suppressed)
    dollars_or_units = metric_column(relation.name, inp.metric)

    params: dict[str, Any] = {"y0": inp.start_period, "y1": inp.end_period}
    where, params = build_where(
        inp.filters,
        relation,
        include_suppressed=inp.include_suppressed,
        extra=[year_predicate(inp.start_period, inp.end_period)],
        params=params,
    )

    group_cols = [sql.Identifier(c) for c in inp.group_by]
    select_parts = list(group_cols) + [
        sql.SQL("sum({}) AS {}").format(
            sql.Identifier(dollars_or_units), sql.Identifier(inp.metric)
        ),
        sql.SQL("count(*) AS source_rows"),
    ]
    query = sql.SQL("SELECT {select} FROM public.{rel}{where}").format(
        select=sql.SQL(", ").join(select_parts),
        rel=sql.Identifier(relation.name),
        where=where,
    )
    if group_cols:
        query = query + sql.SQL(" GROUP BY {} ORDER BY {} DESC NULLS LAST").format(
            sql.SQL(", ").join(group_cols), sql.Identifier(inp.metric)
        )

    try:
        result = run_query(query, params, max_rows=MAX_ROWS)
    except psycopg.errors.QueryCanceled:
        return ToolEnvelope.failed(
            f"The query exceeded the statement timeout aggregating {relation.name}. "
            f"Narrow the filters or reduce group_by.",
            params=key,
        )

    rows = [
        {
            **{c: r[c] for c in inp.group_by},
            inp.metric: float(r[inp.metric]) if r[inp.metric] is not None else None,
            "source_rows": r["source_rows"],
        }
        for r in result.rows
    ]

    states = _states_in_scope(inp, relation, params, where)
    notes = _notes(inp, relation, partial, rows, states)

    envelope = ToolEnvelope(
        rows=rows,
        row_count=len(rows),
        sql=result.sql,
        params=key,
        coverage=Coverage(
            period_start=min(covered),
            period_end=max(covered),
            states=states,
            partial_periods=partial,
            caveats=caveats_for(covered),
        ),
        truncated=result.truncated,
        relation=relation.name,
        notes=notes,
    )
    cache.put(TOOL_NAME, key, version.fingerprint, envelope.model_dump())
    return envelope


def _states_in_scope(inp, relation, params, where) -> list[str]:
    if "state" in inp.filters:
        v = inp.filters["state"]
        return [str(v)] if not isinstance(v, (list, tuple, set)) else sorted(str(x) for x in v)
    q = sql.SQL("SELECT DISTINCT state FROM public.{rel}{where} ORDER BY 1").format(
        rel=sql.Identifier(relation.name), where=where
    )
    try:
        return [r["state"] for r in run_query(q, params).rows]
    except psycopg.errors.QueryCanceled:
        return []


def _notes(inp, relation, partial, rows, states) -> list[str]:
    notes = [
        "BDSA is retail sell-through in covered states only. It is not total market.",
        f"Metric is {inp.metric}. Dollar sales and unit sales are different "
        f"questions and must not be substituted for one another.",
    ]
    if relation.excludes_suppressed:
        notes.append(f"From {relation.name}, which excludes suppressed rows.")
    elif inp.include_suppressed:
        notes.append("Suppressed rows are INCLUDED; this will not match the views.")
    else:
        notes.append("Suppressed rows excluded, matching the materialized views.")
    if partial and len(states) > 1 and "state" not in inp.group_by:
        notes.append(
            f"This total spans {len(states)} states in {', '.join(str(p) for p in partial)}, "
            f"a partial year whose window differs by state. The states are not measured "
            f"over the same number of months, so this figure is not a clean market size."
        )
    # An UNGROUPED aggregate over zero matching rows returns one row of NULLs,
    # not zero rows. Without this check a bad filter looks like a real answer
    # of "null" rather than "nothing matched" -- the exact failure this tool
    # exists to prevent.
    matched_nothing = not rows or all((r.get("source_rows") or 0) == 0 for r in rows)
    if matched_nothing:
        notes.append(
            "No rows matched these filters, so there is no figure to report. "
            "This is an empty result, not a zero market. Verify the filter values "
            "with list_dimension_values -- note that category_l1='Edibles' matches "
            "nothing; edibles are category_l2='Edibles' under "
            "category_l1='Ingestibles'."
        )
    return notes
