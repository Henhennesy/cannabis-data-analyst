"""Check that every figure in an answer came from a tool result this turn.

The chart contract removes transcription error between a query result and a
chart. This does the same job for prose, and it is the only defence that
catches the failure systematically rather than by anticipating it.

Two real cases from testing motivated it:

  * The agent received Inhaleables split by year -- 2025 and 2026 correctly
    separated because a combined total is meaningless -- and then added them in
    prose: "$35.57B combined". No tool returned that number.
  * Asked for top flavors, it hit the 5,000-row cap and wrote "5,000 distinct
    values came back", presenting a row limit as a cardinality.

Both were caught by a human reading carefully. This catches them mechanically.

The output is advisory: it flags figures for a human to check, it does not
block an answer. A false flag costs a glance; a missed fabrication costs a
client relationship, so the bias is deliberately toward flagging.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# Relative tolerance. Wide enough that "$3.87B" matches 3,867,307,583.83 and
# "6.89%" matches 6.8881, narrow enough that a genuinely different number fails.
TOLERANCE = 0.005

SUFFIXES = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mm": 1e6, "million": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
}

# $1,234.56  ·  3.87B  ·  6.89%  ·  266,382,172.26  ·  37
#
# Suffix handling is fussy for a reason. A naive `[KkMmBb]` after optional
# whitespace turns "top 5 brands" into 5 billion and "37 BDSA-covered states"
# into 37 billion -- both observed. So:
#   * single-letter suffixes must be glued to the digits (3.87B, not "5 b")
#   * every suffix must not be the start of a longer word
_NUMBER = re.compile(
    r"""
    (?P<currency>\$)?
    (?P<digits>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)
    (?:
        \s*(?P<suffix_word>billion|million|thousand|bn|mm)(?![A-Za-z])
      | (?P<suffix_char>[KkMmBb])(?![A-Za-z])
    )?
    (?P<percent>\s*%)?
    """,
    re.VERBOSE | re.IGNORECASE,
)


@dataclass
class Claim:
    """A number stated in prose."""
    text: str
    value: float
    is_percent: bool
    start: int
    end: int
    matched: bool = False
    matched_against: float | None = None


@dataclass
class Verification:
    claims: list[Claim] = field(default_factory=list)
    unverified: list[Claim] = field(default_factory=list)
    checked_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.unverified


def _parse(match: re.Match) -> tuple[float, bool] | None:
    raw = match.group("digits").replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    suffix = (match.group("suffix_word") or match.group("suffix_char") or "").lower()
    if suffix:
        value *= SUFFIXES.get(suffix, 1.0)
    return value, bool(match.group("percent"))


def collect_tool_values(envelopes: Iterable[Any]) -> set[float]:
    """Every number a tool actually returned this turn.

    Includes row counts and state counts, because answers legitimately quote
    them ("37 covered states", "5,000 rows").
    """
    values: set[float] = set()

    def add(v: Any) -> None:
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            values.add(float(v))

    for env in envelopes:
        add(env.row_count)
        add(len(env.coverage.states))
        for y in (env.coverage.period_start, env.coverage.period_end):
            add(y)
        for y in env.coverage.partial_periods:
            add(y)
        for row in env.rows:
            for v in row.values():
                add(v)
    return values


def _matches(claim_value: float, is_percent: bool, pool: set[float]) -> float | None:
    """A tool value the claim plausibly restates.

    Shares are stored as fractions but usually quoted as percentages, so a
    percent claim is checked against both the number and the number over 100.
    """
    candidates = [claim_value]
    if is_percent:
        candidates.append(claim_value / 100.0)
    else:
        # An unmarked share, e.g. "a 0.07 share" against a stored 0.068881.
        candidates.append(claim_value * 100.0)

    for candidate in candidates:
        for value in pool:
            scale = max(abs(value), abs(candidate), 1.0)
            if abs(candidate - value) / scale <= TOLERANCE:
                return value
    return None


def _is_worth_checking(claim: Claim, text: str) -> bool:
    """Filter prose numbers from data claims.

    Bare small integers are almost always prose -- "top 5 brands", "two
    caveats", "three ways forward" -- and flagging them would bury the real
    findings in noise. A figure destined for a deck carries a currency symbol,
    a percent sign, a magnitude suffix, a decimal point, or a thousands
    separator; or it is simply large.
    """
    token = claim.text
    if claim.is_percent:
        return True
    if "$" in token or "," in token or "." in token:
        return True
    if re.search(r"(billion|million|thousand|bn|mm|[KkMmBb])$", token.strip(),
                 re.IGNORECASE):
        return True

    # A bare four-digit year is prose context ("in 2025"), not a figure. The
    # claim being made alongside it is the dollar amount, and THAT gets checked.
    # Reporting on a period that is not loaded is already prevented upstream --
    # every tool refuses an out-of-coverage period outright.
    if 1900 <= claim.value <= 2100 and float(claim.value).is_integer():
        return False

    return claim.value >= 100


def verify(answer: str, envelopes: Iterable[Any]) -> Verification:
    """Flag figures in `answer` that no tool result this turn supports."""
    pool = collect_tool_values(envelopes)
    result = Verification()

    for match in _NUMBER.finditer(answer or ""):
        parsed = _parse(match)
        if parsed is None:
            continue
        value, is_percent = parsed
        claim = Claim(
            text=match.group(0).strip(),
            value=value,
            is_percent=is_percent,
            start=match.start(),
            end=match.end(),
        )
        if not _is_worth_checking(claim, answer):
            continue

        result.checked_count += 1
        hit = _matches(value, is_percent, pool)
        if hit is None:
            result.claims.append(claim)
            result.unverified.append(claim)
        else:
            claim.matched = True
            claim.matched_against = hit
            result.claims.append(claim)

    return result
