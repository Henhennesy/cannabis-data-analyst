"""The structured envelope every tool returns.

`sql` is surfaced in the UI so any number can be audited before it goes into a
deck. `coverage` travels with every result because a BDSA figure is meaningless
without its period and its state set.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Coverage(BaseModel):
    """The period and state set a figure applies to.

    `caveats` is not decoration. 2026 is a partial year whose width is unknown
    and varies by state -- nothing in the data records any state's YTD cutoff.
    A 2026 figure without that attached invites a wrong conclusion.
    """

    period_start: int | None = None
    period_end: int | None = None
    states: list[str] = Field(default_factory=list)
    partial_periods: list[int] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)

    def describe(self) -> str:
        if self.period_start is None:
            period = "unknown period"
        elif self.period_start == self.period_end:
            period = str(self.period_start)
        else:
            period = f"{self.period_start}-{self.period_end}"
        n = len(self.states)
        states = "no states" if n == 0 else (
            self.states[0] if n == 1 else f"{n} states"
        )
        text = f"{period}, {states}"
        if self.partial_periods:
            text += f" (partial: {', '.join(str(p) for p in self.partial_periods)})"
        return text


class ToolEnvelope(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    sql: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    coverage: Coverage = Field(default_factory=Coverage)
    truncated: bool = False

    # Not in the original spec, but the agent needs to distinguish "no rows
    # matched" from "the query failed" -- and must say so either way rather
    # than estimating.
    relation: str | None = None
    error: str | None = None
    notes: list[str] = Field(default_factory=list)

    @classmethod
    def failed(cls, message: str, *, sql_text: str = "", params: dict | None = None) -> "ToolEnvelope":
        return cls(error=message, sql=sql_text, params=params or {})

    @property
    def is_empty(self) -> bool:
        return self.row_count == 0 and self.error is None
