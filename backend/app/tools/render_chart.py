"""render_chart -- the chart contract.

The model never emits data points. It names a prior tool call and the columns
to plot, and the frontend renders that against rows it already holds. This
eliminates transcription error between a query result and a chart: there is no
step at which a number is retyped.

Validation happens here rather than in the browser so the model gets told, in
the same turn, that it named a column that does not exist -- and can fix it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..envelope import Coverage, ToolEnvelope

TOOL_NAME = "render_chart"

CHART_TYPES = ("bar", "line", "stacked_bar", "table")

ANTHROPIC_TOOL = {
    "name": TOOL_NAME,
    "description": (
        "Draw a chart from a PREVIOUS tool result in this turn. You do not supply "
        "data points -- you name the tool call and the columns, and the interface "
        "renders it against the rows it already has. "
        "source_tool_call is the tool_use id of the earlier call whose rows you want "
        "plotted. x, y and series must be column names present in that result. "
        "Use 'table' when the rows are the point and a chart would add nothing. "
        "The caption must state the period and the state set, because a chart gets "
        "screenshotted into a deck without its surrounding text."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": list(CHART_TYPES)},
            "source_tool_call": {
                "type": "string",
                "description": "tool_use id of the earlier call supplying the rows.",
            },
            "x": {"type": "string", "description": "Column for the category axis."},
            "y": {"type": "string", "description": "Column for the value axis."},
            "series": {
                "type": "string",
                "description": "Optional column to split into multiple series.",
            },
            "title": {"type": "string"},
            "caption": {
                "type": "string",
                "description": "Must carry the period and the state set.",
            },
        },
        "required": ["type", "source_tool_call", "x", "y", "title", "caption"],
        "additionalProperties": False,
    },
}


class RenderChartInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    source_tool_call: str
    x: str
    y: str
    title: str
    caption: str
    series: str | None = None

    @field_validator("type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in CHART_TYPES:
            raise ValueError(f"unknown chart type {v!r}; expected one of {CHART_TYPES}")
        return v


def render_chart(
    inp: RenderChartInput, tool_results: dict[str, ToolEnvelope] | None = None
) -> ToolEnvelope:
    """Validate a chart spec against the result it references.

    Returns an envelope carrying the spec. The frontend reads the spec and
    renders it against the source envelope's rows -- which it already has,
    because every tool_result event ships the full row set.
    """
    results = tool_results or {}

    source = results.get(inp.source_tool_call)
    if source is None:
        known = ", ".join(results) or "none yet"
        return ToolEnvelope.failed(
            f"No tool call {inp.source_tool_call!r} in this turn. Charts must "
            f"reference a result you already fetched. Available: {known}.",
            params=inp.model_dump(),
        )

    if source.error:
        return ToolEnvelope.failed(
            f"Tool call {inp.source_tool_call!r} failed, so there is nothing to plot: "
            f"{source.error}",
            params=inp.model_dump(),
        )

    if not source.rows:
        return ToolEnvelope.failed(
            f"Tool call {inp.source_tool_call!r} returned no rows. An empty chart "
            f"would imply a zero market; say that nothing matched instead.",
            params=inp.model_dump(),
        )

    columns = set(source.rows[0].keys())
    named = {"x": inp.x, "y": inp.y}
    if inp.series:
        named["series"] = inp.series

    missing = {role: col for role, col in named.items() if col not in columns}
    if missing:
        detail = ", ".join(f"{role}={col!r}" for role, col in missing.items())
        return ToolEnvelope.failed(
            f"Column(s) not present in {inp.source_tool_call}: {detail}. "
            f"That result has: {', '.join(sorted(columns))}.",
            params=inp.model_dump(),
        )

    numeric = [
        r[inp.y] for r in source.rows[:50]
        if isinstance(r.get(inp.y), (int, float)) and not isinstance(r.get(inp.y), bool)
    ]
    if inp.type != "table" and not numeric:
        return ToolEnvelope.failed(
            f"Column {inp.y!r} is not numeric, so it cannot be the value axis. "
            f"Use type='table', or pick a numeric column.",
            params=inp.model_dump(),
        )

    spec = {
        "type": inp.type,
        "source_tool_call": inp.source_tool_call,
        "x": inp.x,
        "y": inp.y,
        "series": inp.series,
        "title": inp.title,
        "caption": inp.caption,
    }

    notes = [
        f"Chart accepted. It renders against the {source.row_count} row(s) already "
        f"returned by {inp.source_tool_call} -- do not restate those numbers in prose "
        f"unless the reader needs a specific one.",
        f"Source coverage: {source.coverage.describe()}.",
    ]
    if source.truncated:
        notes.append(
            "The source result was TRUNCATED, so the chart shows only the rows "
            "returned. Say so in the caption if the tail matters."
        )

    return ToolEnvelope(
        rows=[spec],
        row_count=1,
        sql="",
        params=inp.model_dump(),
        # The chart inherits its source's coverage; a chart with a different
        # period or state set than the data behind it would be a lie.
        coverage=Coverage(
            period_start=source.coverage.period_start,
            period_end=source.coverage.period_end,
            states=source.coverage.states,
            partial_periods=source.coverage.partial_periods,
            caveats=source.coverage.caveats,
        ),
        truncated=False,
        relation="(chart spec)",
        notes=notes,
    )
