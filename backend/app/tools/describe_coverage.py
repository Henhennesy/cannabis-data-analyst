"""describe_coverage -- what is actually in the database.

The agent calls this before answering anything that implies a recent period,
so it can never report on a period that is not loaded. It is also the only
place that states the 2026 partial-year caveat authoritatively.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .. import cache
from ..dataset import caveats_for, data_fingerprint, partial_years_for
from ..db import run_query
from ..envelope import Coverage, ToolEnvelope
from ..schema_registry import MV_CATEGORY

TOOL_NAME = "describe_coverage"

ANTHROPIC_TOOL = {
    "name": TOOL_NAME,
    "description": (
        "Returns exactly what data is loaded: which years, which states, row counts "
        "and dollar totals by state and year, and which periods are partial. "
        "Call this BEFORE answering any question that implies a recent or current "
        "period, so you never report on a period that is not in the data. Takes no "
        "arguments."
    ),
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}


class DescribeCoverageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Routed to the category rollup: the same answer from the fact table needs a
# 9.19s aggregate that does not fit the 8s statement timeout.
_SQL = f"""
SELECT state,
       period_year,
       sum(total_sales) AS dollar_sales,
       sum(total_units) AS unit_sales
FROM public.{MV_CATEGORY}
GROUP BY state, period_year
ORDER BY state, period_year
"""


def describe_coverage(_: DescribeCoverageInput | None = None) -> ToolEnvelope:
    version = data_fingerprint()

    cached = cache.get(TOOL_NAME, {}, version.fingerprint)
    if cached is not None:
        return ToolEnvelope.model_validate(cached)

    result = run_query(_SQL)

    years = sorted({r["period_year"] for r in result.rows})
    states = sorted({r["state"] for r in result.rows})
    partial = partial_years_for(years)

    # Deliberately NOT calling source_file_summary() here. It groups 7.45M rows
    # by source_file -- a full scan that exceeds the 8s budget on a cold cache,
    # and describe_coverage is the FIRST tool called in every session, so a
    # timeout here fails the session's opening move. Load provenance is
    # available from the maintenance helper when it is actually wanted.
    notes = [
        "BDSA is retail sell-through in covered states only. It is not total market.",
        f"Data version {version.fingerprint}. The schema has no load-timestamp "
        f"column; this fingerprint changes whenever the data is reloaded.",
    ]
    missing = _states_missing_a_year(result.rows, years)
    if missing:
        notes.append(
            "States missing at least one year: " + ", ".join(missing) +
            ". Totals for the missing year exclude them."
        )

    envelope = ToolEnvelope(
        rows=[
            {
                "state": r["state"],
                "period_year": r["period_year"],
                "dollar_sales": float(r["dollar_sales"]) if r["dollar_sales"] is not None else None,
                "unit_sales": float(r["unit_sales"]) if r["unit_sales"] is not None else None,
            }
            for r in result.rows
        ],
        row_count=result.row_count,
        sql=result.sql,
        params={},
        coverage=Coverage(
            period_start=years[0] if years else None,
            period_end=years[-1] if years else None,
            states=states,
            partial_periods=partial,
            caveats=caveats_for(years),
        ),
        truncated=result.truncated,
        relation=MV_CATEGORY,
        notes=notes,
    )
    cache.put(TOOL_NAME, {}, version.fingerprint, envelope.model_dump())
    return envelope


def _states_missing_a_year(rows: list[dict], years: list[int]) -> list[str]:
    seen: dict[str, set[int]] = {}
    for r in rows:
        seen.setdefault(r["state"], set()).add(r["period_year"])
    wanted = set(years)
    return sorted(s for s, ys in seen.items() if ys != wanted)
