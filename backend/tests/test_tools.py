"""Tests for list_dimension_values and describe_coverage.

Known answers come from reports/baseline_metrics.md, computed directly against
the database after the 2026-07-31 reload. If a legitimate data load changes
them, that document is regenerated and these constants move with it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app import cache
from backend.app.dataset import data_fingerprint
from backend.app.db import run_query, safe_identifier
from backend.app.tools import (
    DescribeCoverageInput,
    ListDimensionValuesInput,
    describe_coverage,
    list_dimension_values,
)

pytestmark = pytest.mark.db

EXPECTED_STATE_COUNT = 37
EXPECTED_YEARS = [2025, 2026]
EXPECTED_CATEGORY_L1 = {
    "Inhaleables", "Ingestibles", "Topicals", "All Accessories", "Other Cannabis",
}


# ---------------------------------------------------------------------------
# list_dimension_values
# ---------------------------------------------------------------------------

def test_lists_top_level_categories_with_correct_spelling():
    env = list_dimension_values(ListDimensionValuesInput(dimension="category_l1"))
    values = {r["value"] for r in env.rows}
    assert values == EXPECTED_CATEGORY_L1
    assert "Inhalables" not in values  # the plausible misspelling
    assert env.error is None


def test_nested_filter_reveals_edibles_under_ingestibles():
    """The exact call that stops the agent guessing category_l1='Edibles'."""
    env = list_dimension_values(
        ListDimensionValuesInput(
            dimension="category_l2", filter_by={"category_l1": "Ingestibles"}
        )
    )
    values = {r["value"] for r in env.rows}
    assert "Edibles" in values
    assert "Sublinguals" in values


def test_filtering_on_a_nonexistent_value_returns_empty_not_wrong():
    """A bad filter must produce zero rows and say so -- never a silent subset."""
    env = list_dimension_values(
        ListDimensionValuesInput(
            dimension="category_l2", filter_by={"category_l1": "Edibles"}
        )
    )
    assert env.rows == []
    assert env.row_count == 0
    assert env.is_empty
    assert any("No values matched" in n for n in env.notes)


def test_fast_acting_values_are_the_two_literals():
    env = list_dimension_values(ListDimensionValuesInput(dimension="fast_acting"))
    values = {r["value"] for r in env.rows if r["value"] is not None}
    assert values == {"Fast Acting", "Not Fast Acting"}


def test_states_are_complete():
    env = list_dimension_values(ListDimensionValuesInput(dimension="state"))
    assert env.row_count == EXPECTED_STATE_COUNT
    assert "Maine" in {r["value"] for r in env.rows}
    assert "Arkansas" in {r["value"] for r in env.rows}


def test_unknown_dimension_is_rejected_before_any_sql_runs():
    with pytest.raises(ValidationError):
        ListDimensionValuesInput(dimension="brand_name")
    with pytest.raises(ValidationError):
        ListDimensionValuesInput(dimension="category_l1", filter_by={"nope": "x"})


def test_sql_injection_in_a_dimension_name_is_rejected():
    with pytest.raises(ValidationError):
        ListDimensionValuesInput(dimension="state; DROP TABLE bdsa_sales--")
    with pytest.raises(ValueError):
        safe_identifier("state; DROP TABLE bdsa_sales--")


def test_filter_values_are_parameterised_not_interpolated():
    """A hostile filter VALUE must be data, not SQL. It should simply match
    nothing rather than execute."""
    env = list_dimension_values(
        ListDimensionValuesInput(
            dimension="category_l2",
            filter_by={"category_l1": "Ingestibles'; DROP TABLE bdsa_sales--"},
        )
    )
    assert env.rows == []
    # The table is still there.
    assert run_query("SELECT count(*) AS n FROM public.bdsa_sales").rows[0]["n"] > 0


def test_unlistable_dimension_is_refused_with_guidance_not_a_timeout():
    """`product` has 3.4M distinct values and takes 73s to group on the fact
    table. It must be refused with an explanation, not attempted."""
    env = list_dimension_values(ListDimensionValuesInput(dimension="product"))
    assert env.error is not None
    assert "narrowing" in env.error
    assert "filter_by" in env.error
    assert env.rows == []


def test_unlistable_dimension_is_allowed_once_narrowed():
    env = list_dimension_values(
        ListDimensionValuesInput(
            dimension="product",
            filter_by={"category_l1": "Ingestibles", "category_l2": "Edibles"},
        )
    )
    assert env.error is None
    assert env.row_count > 0


def test_envelope_carries_auditable_sql_and_coverage():
    env = list_dimension_values(ListDimensionValuesInput(dimension="category_l1"))
    assert "SELECT" in env.sql.upper()
    assert env.relation is not None
    assert env.coverage.period_start == 2025
    assert env.coverage.period_end == 2026
    assert env.coverage.states  # never an unscoped figure
    assert 2026 in env.coverage.partial_periods
    assert any("PARTIAL" in c for c in env.coverage.caveats)


def test_results_are_cached_on_the_dataset_fingerprint():
    cache.clear()
    fp = data_fingerprint().fingerprint
    key = {"dimension": "category_l1", "filter_by": {}}
    assert cache.get("list_dimension_values", key, fp) is None

    list_dimension_values(ListDimensionValuesInput(dimension="category_l1"))
    assert cache.get("list_dimension_values", key, fp) is not None

    # A different fingerprint (i.e. after a reload) must miss.
    assert cache.get("list_dimension_values", key, "stale-fingerprint") is None


# ---------------------------------------------------------------------------
# describe_coverage
# ---------------------------------------------------------------------------

def test_coverage_reports_both_years_and_every_state():
    env = describe_coverage(DescribeCoverageInput())
    assert env.coverage.period_start == EXPECTED_YEARS[0]
    assert env.coverage.period_end == EXPECTED_YEARS[-1]
    assert len(env.coverage.states) == EXPECTED_STATE_COUNT


def test_coverage_flags_2026_as_partial_with_the_reason():
    """The caveat the reload could not fix: 2026's width is unknown and
    varies by state, so cross-state 2026 totals are not meaningful."""
    env = describe_coverage(DescribeCoverageInput())
    assert env.coverage.partial_periods == [2026]
    caveat = " ".join(env.coverage.caveats)
    assert "PARTIAL" in caveat
    assert "not comparable" in caveat


def test_coverage_states_that_this_is_not_total_market():
    env = describe_coverage(DescribeCoverageInput())
    assert any("not total market" in n.lower() for n in env.notes)


def test_coverage_reports_no_state_missing_a_year_after_the_reload():
    env = describe_coverage(DescribeCoverageInput())
    assert not any("missing at least one year" in n for n in env.notes)


def test_coverage_has_one_row_per_state_year():
    env = describe_coverage(DescribeCoverageInput())
    assert env.row_count == EXPECTED_STATE_COUNT * len(EXPECTED_YEARS)
    pairs = {(r["state"], r["period_year"]) for r in env.rows}
    assert len(pairs) == env.row_count


def test_coverage_includes_a_data_version_fingerprint():
    """There is no load-timestamp column, so the fingerprint is how a reload
    is detected. It must be reported, not silently assumed."""
    env = describe_coverage(DescribeCoverageInput())
    assert any("Data version" in n for n in env.notes)
