"""get_market_size and get_segment_penetration, against the live database.

Known answers come from reports/baseline_metrics.md, computed directly after
the 2026-07-31 reload. A legitimate data load moves them; that document is
regenerated and these constants move with it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.db import run_query
from backend.app.tools import (
    GetMarketSizeInput,
    GetSegmentPenetrationInput,
    get_market_size,
    get_segment_penetration,
)
from backend.app.tools.filters import merge_numerator_filters

pytestmark = pytest.mark.db

# --- reports/baseline_metrics.md -------------------------------------------
EDIBLES = {"category_l1": "Ingestibles", "category_l2": "Edibles"}
FA_2025_DOLLARS = 266_382_172.26
EDIBLES_2025_DOLLARS = 3_867_307_583.83
FA_SHARE_2025_DOLLARS = 0.068881
FA_SHARE_2025_UNITS = 0.055523
NATIONAL_2025_DOLLARS = 28_519_734_771.25
EXPECTED_STATES = 37


def approx(value: float, expected: float, tol: float = 0.005) -> bool:
    """Relative tolerance. Tight enough to catch a wrong filter, loose enough
    to survive float summation order."""
    return abs(value - expected) <= abs(expected) * tol


# ---------------------------------------------------------------------------
# get_market_size
# ---------------------------------------------------------------------------

def test_national_2025_dollars_matches_the_baseline():
    env = get_market_size(
        GetMarketSizeInput(metric="dollar_sales", start_period=2025, end_period=2025)
    )
    assert env.error is None
    total = env.rows[0]["dollar_sales"]
    assert approx(total, NATIONAL_2025_DOLLARS)
    assert len(env.coverage.states) == EXPECTED_STATES


def test_edibles_2025_sizing_uses_the_nested_category_path():
    env = get_market_size(
        GetMarketSizeInput(
            metric="dollar_sales", filters=EDIBLES, start_period=2025, end_period=2025
        )
    )
    assert approx(env.rows[0]["dollar_sales"], EDIBLES_2025_DOLLARS)


def test_the_naive_edibles_filter_returns_empty_not_a_number():
    """category_l1='Edibles' is the trap. It must yield nothing, and say so.

    Note the shape: an UNGROUPED aggregate over no matching rows returns one
    row of NULLs rather than zero rows, so 'did anything match' has to be read
    from source_rows, not from row_count.
    """
    env = get_market_size(
        GetMarketSizeInput(
            metric="dollar_sales",
            filters={"category_l1": "Edibles"},
            start_period=2025,
            end_period=2025,
        )
    )
    assert env.rows[0]["dollar_sales"] is None
    assert env.rows[0]["source_rows"] == 0
    assert any("empty result, not a zero market" in n for n in env.notes)


def test_a_grouped_query_with_no_matches_returns_no_rows_at_all():
    """The other shape of the same question, for contrast."""
    env = get_market_size(
        GetMarketSizeInput(
            metric="dollar_sales",
            filters={"category_l1": "Edibles"},
            start_period=2025,
            end_period=2025,
            group_by=["state"],
        )
    )
    assert env.rows == []
    assert env.row_count == 0
    assert any("empty result, not a zero market" in n for n in env.notes)


def test_group_by_state_sums_to_the_national_total():
    """Internal consistency: the parts must equal the whole."""
    grouped = get_market_size(
        GetMarketSizeInput(
            metric="dollar_sales", start_period=2025, end_period=2025,
            group_by=["state"],
        )
    )
    assert grouped.row_count == EXPECTED_STATES
    assert approx(sum(r["dollar_sales"] for r in grouped.rows), NATIONAL_2025_DOLLARS)


def test_dollars_and_units_are_not_interchangeable():
    dollars = get_market_size(
        GetMarketSizeInput(metric="dollar_sales", filters=EDIBLES,
                           start_period=2025, end_period=2025)
    ).rows[0]["dollar_sales"]
    units = get_market_size(
        GetMarketSizeInput(metric="unit_sales", filters=EDIBLES,
                           start_period=2025, end_period=2025)
    ).rows[0]["unit_sales"]
    assert dollars != units
    assert not approx(dollars, units, tol=0.5)


def test_period_outside_coverage_is_refused_not_answered_with_zero():
    env = get_market_size(
        GetMarketSizeInput(metric="dollar_sales", start_period=2024, end_period=2024)
    )
    assert env.error is not None
    assert "No data for 2024" in env.error
    assert env.rows == []


def test_summing_a_complete_and_a_partial_year_is_refused():
    """2025 + 2026 in one figure mixes twelve months with an unknown number."""
    env = get_market_size(
        GetMarketSizeInput(metric="dollar_sales", start_period=2025, end_period=2026)
    )
    assert env.error is not None
    assert "partial year" in env.error
    assert "group_by" in env.error


def test_the_same_range_is_allowed_when_broken_out_by_year():
    env = get_market_size(
        GetMarketSizeInput(
            metric="dollar_sales", start_period=2025, end_period=2026,
            group_by=["period_year"],
        )
    )
    assert env.error is None
    assert env.row_count == 2
    assert env.coverage.partial_periods == [2026]


def test_2026_multi_state_total_carries_a_prominent_caveat():
    env = get_market_size(
        GetMarketSizeInput(metric="dollar_sales", start_period=2026, end_period=2026)
    )
    assert env.error is None
    assert any("not measured over the same number of months" in n for n in env.notes)
    assert 2026 in env.coverage.partial_periods


def test_unknown_dimensions_are_rejected_before_sql_is_built():
    with pytest.raises(ValidationError):
        GetMarketSizeInput(metric="dollar_sales", start_period=2025, end_period=2025,
                           filters={"made_up": "x"})
    with pytest.raises(ValidationError):
        GetMarketSizeInput(metric="dollar_sales", start_period=2025, end_period=2025,
                           group_by=["made_up"])
    with pytest.raises(ValidationError):
        GetMarketSizeInput(metric="revenue", start_period=2025, end_period=2025)


def test_envelope_exposes_sql_and_never_an_unscoped_figure():
    env = get_market_size(
        GetMarketSizeInput(metric="dollar_sales", filters=EDIBLES,
                           start_period=2025, end_period=2025)
    )
    assert "sum(" in env.sql.lower()
    assert env.coverage.period_start == 2025
    assert env.coverage.states
    assert any("not total market" in n.lower() for n in env.notes)


# ---------------------------------------------------------------------------
# get_segment_penetration -- the Milestone 3 target
# ---------------------------------------------------------------------------

def test_fast_acting_share_of_national_edibles_2025_dollars():
    """THE milestone 3 regression target: 6.8881% of dollars, 37 states."""
    env = get_segment_penetration(
        GetSegmentPenetrationInput(
            numerator_filters={"fast_acting": "Fast Acting"},
            denominator_filters=EDIBLES,
            period=2025,
            metric="dollar_sales",
        )
    )
    assert env.error is None
    row = env.rows[0]
    assert approx(row["numerator"], FA_2025_DOLLARS)
    assert approx(row["denominator"], EDIBLES_2025_DOLLARS)
    assert approx(row["ratio"], FA_SHARE_2025_DOLLARS)
    assert row["state_count"] == EXPECTED_STATES


def test_fast_acting_share_of_national_edibles_2025_units():
    """The unit share is 5.5523%, materially different from the dollar share."""
    env = get_segment_penetration(
        GetSegmentPenetrationInput(
            numerator_filters={"fast_acting": "Fast Acting"},
            denominator_filters=EDIBLES,
            period=2025,
            metric="unit_sales",
        )
    )
    assert approx(env.rows[0]["ratio"], FA_SHARE_2025_UNITS)


def test_dollar_and_unit_shares_differ_materially():
    kw = dict(numerator_filters={"fast_acting": "Fast Acting"},
              denominator_filters=EDIBLES, period=2025)
    d = get_segment_penetration(GetSegmentPenetrationInput(metric="dollar_sales", **kw))
    u = get_segment_penetration(GetSegmentPenetrationInput(metric="unit_sales", **kw))
    assert abs(d.rows[0]["ratio"] - u.rows[0]["ratio"]) > 0.01


def test_penetration_matches_hand_written_sql():
    """Independent verification: the tool must agree with SQL written by hand
    straight against the fact table."""
    env = get_segment_penetration(
        GetSegmentPenetrationInput(
            numerator_filters={"fast_acting": "Fast Acting"},
            denominator_filters=EDIBLES, period=2025, metric="dollar_sales",
        )
    )
    manual = run_query(
        """
        SELECT sum(total_retail_sales) FILTER (WHERE fast_acting = 'Fast Acting')
                 / NULLIF(sum(total_retail_sales), 0) AS share
        FROM public.bdsa_sales
        WHERE category_l1 = 'Ingestibles' AND category_l2 = 'Edibles'
          AND period_year = 2025 AND NOT is_suppressed
        """
    ).rows[0]["share"]
    assert approx(env.rows[0]["ratio"], float(manual), tol=0.0001)


def test_the_ratio_can_never_exceed_one():
    """The numerator inherits the denominator's filters, so a numerator that
    would otherwise span the whole market is still confined to edibles."""
    env = get_segment_penetration(
        GetSegmentPenetrationInput(
            numerator_filters={"fast_acting": "Fast Acting"},
            denominator_filters=EDIBLES, period=2025, metric="dollar_sales",
        )
    )
    assert 0 <= env.rows[0]["ratio"] <= 1


def test_contradictory_numerator_is_rejected():
    env = get_segment_penetration(
        GetSegmentPenetrationInput(
            numerator_filters={"category_l2": "Vape"},
            denominator_filters=EDIBLES, period=2025, metric="dollar_sales",
        )
    )
    assert env.error is not None
    assert "contradicts" in env.error


def test_merge_makes_the_numerator_a_subset():
    merged = merge_numerator_filters(EDIBLES, {"fast_acting": "Fast Acting"})
    assert merged == {**EDIBLES, "fast_acting": "Fast Acting"}
    with pytest.raises(ValueError, match="contradicts"):
        merge_numerator_filters({"state": "Maine"}, {"state": "Ohio"})


def test_empty_denominator_is_refused_with_the_edibles_hint():
    env = get_segment_penetration(
        GetSegmentPenetrationInput(
            numerator_filters={"fast_acting": "Fast Acting"},
            denominator_filters={"category_l1": "Edibles"},  # the trap
            period=2025, metric="dollar_sales",
        )
    )
    assert env.error is not None
    assert "category_l1='Edibles' matches nothing" in env.error


def test_denominator_cannot_be_the_whole_market_by_omission():
    env = get_segment_penetration(
        GetSegmentPenetrationInput(
            numerator_filters={"fast_acting": "Fast Acting"},
            denominator_filters={}, period=2025, metric="dollar_sales",
        )
    )
    assert env.error is not None
    assert "entire market" in env.error


def test_state_restriction_scopes_both_sides():
    env = get_segment_penetration(
        GetSegmentPenetrationInput(
            numerator_filters={"fast_acting": "Fast Acting"},
            denominator_filters=EDIBLES, period=2025, metric="dollar_sales",
            states=["Maine"],
        )
    )
    assert env.error is None
    assert env.coverage.states == ["Maine"]
    assert env.rows[0]["state_count"] == 1
    assert 0 <= env.rows[0]["ratio"] <= 1


def test_2026_penetration_is_allowed_and_explains_why():
    """A ratio survives the partial year; an absolute total does not."""
    env = get_segment_penetration(
        GetSegmentPenetrationInput(
            numerator_filters={"fast_acting": "Fast Acting"},
            denominator_filters=EDIBLES, period=2026, metric="dollar_sales",
        )
    )
    assert env.error is None
    assert 0 <= env.rows[0]["ratio"] <= 1
    assert any("cancels between numerator and denominator" in n for n in env.notes)


def test_period_outside_coverage_is_refused():
    env = get_segment_penetration(
        GetSegmentPenetrationInput(
            numerator_filters={"fast_acting": "Fast Acting"},
            denominator_filters=EDIBLES, period=2024, metric="dollar_sales",
        )
    )
    assert env.error is not None
    assert "No data for 2024" in env.error
