"""A truncated result must never be readable as a count.

Found live: asked for top flavors in edibles, get_market_size grouped by flavor
and hit the 5,000-row cap. The agent then wrote "5,000 distinct values came
back", presenting the row cap as the cardinality. The rows themselves were
right -- ordering happens before LIMIT, so the top of the list was complete --
but the count was not, and it read as authoritative.
"""

from __future__ import annotations

import pytest

from backend.app.config import MAX_ROWS
from backend.app.tools import GetMarketSizeInput, get_market_size

pytestmark = pytest.mark.db

EDIBLES = {"category_l1": "Ingestibles", "category_l2": "Edibles"}


def test_a_truncated_group_by_says_it_is_a_cap_not_a_count():
    env = get_market_size(GetMarketSizeInput(
        metric="dollar_sales", filters=EDIBLES,
        start_period=2025, end_period=2025, group_by=["product"],
    ))
    assert env.error is None
    assert env.truncated is True
    assert env.row_count == MAX_ROWS

    warning = next((n for n in env.notes if "TRUNCATED" in n), None)
    assert warning is not None
    assert "NOT the number" in warning
    assert "Do not report it as a count" in warning
    # The ordering guarantee matters: the head of the list IS complete.
    assert "descending" in warning


def test_an_untruncated_result_carries_no_truncation_note():
    """The warning has to stay specific or it becomes noise."""
    env = get_market_size(GetMarketSizeInput(
        metric="dollar_sales", filters=EDIBLES,
        start_period=2025, end_period=2025, group_by=["state"],
    ))
    assert env.truncated is False
    assert env.row_count == 37
    assert not any("TRUNCATED" in n for n in env.notes)


def test_the_head_of_a_truncated_ranking_is_still_correct():
    """Ordering is applied before the cap, so the top N is trustworthy even
    when the tail is missing -- that is why the note says so."""
    big = get_market_size(GetMarketSizeInput(
        metric="dollar_sales", filters=EDIBLES,
        start_period=2025, end_period=2025, group_by=["flavor"],
    ))
    values = [r["dollar_sales"] for r in big.rows[:50] if r["dollar_sales"] is not None]
    assert values == sorted(values, reverse=True)
