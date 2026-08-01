"""Guards against the model re-deriving a figure the tools refused to produce.

Found in live testing: asked for the vape market, the agent called
get_market_size grouped by year, received 2025 and 2026 correctly separated,
then added them together in prose and reported "$35.57B combined" -- exactly
the total the tool refuses to return. The guard held at the tool boundary and
the model routed around it with arithmetic.

The systematic fix is the chart-contract verifier in Milestone 7 (flag inline
numbers that appear in no tool result). These are the two defences that ship
now: a warning carried on the data itself, and an explicit prompt rule.
"""

from __future__ import annotations

import pytest

from backend.app.agent import load_system_prompt
from backend.app.tools import GetMarketSizeInput, get_market_size

pytestmark = pytest.mark.db

INHALEABLES = {"category_l1": "Inhaleables"}


def test_a_year_split_result_warns_against_totalling_it():
    env = get_market_size(GetMarketSizeInput(
        metric="dollar_sales", filters=INHALEABLES,
        start_period=2025, end_period=2026, group_by=["period_year"],
    ))
    assert env.error is None
    assert env.row_count == 2

    warning = next((n for n in env.notes if "DO NOT TOTAL" in n), None)
    assert warning is not None, "a mixed complete/partial year result must warn"
    assert "2026" in warning and "2025" in warning


def test_a_single_year_result_carries_no_such_warning():
    """The warning must be specific, or it becomes noise the model tunes out."""
    env = get_market_size(GetMarketSizeInput(
        metric="dollar_sales", filters=INHALEABLES,
        start_period=2025, end_period=2025, group_by=["period_year"],
    ))
    assert not any("DO NOT TOTAL" in n for n in env.notes)


def test_a_result_grouped_by_something_else_carries_no_warning():
    env = get_market_size(GetMarketSizeInput(
        metric="dollar_sales", filters=INHALEABLES,
        start_period=2025, end_period=2025, group_by=["category_l2"],
    ))
    assert not any("DO NOT TOTAL" in n for n in env.notes)


def test_the_ungrouped_total_is_still_refused_outright():
    """The tool-level guard has to stay -- the note is a second line of
    defence, not a replacement for it."""
    env = get_market_size(GetMarketSizeInput(
        metric="dollar_sales", filters=INHALEABLES,
        start_period=2025, end_period=2026,
    ))
    assert env.error is not None
    assert "partial year" in env.error


def test_system_prompt_forbids_arithmetic_on_retrieved_figures():
    text = load_system_prompt()
    assert "Arithmetic on retrieved figures produces a figure that was not retrieved" in text
    assert "Never total rows that a tool deliberately split" in text
    # The aside is where it actually slipped through, so it is called out.
    assert "in passing" in text
