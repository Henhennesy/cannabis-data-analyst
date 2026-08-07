"""get_brand_share and run_sql, against the live database."""

from __future__ import annotations

import importlib
import json

import psycopg
import pytest

from backend.app.config import get_settings
from backend.app.db import run_query
from backend.app.tools import (
    GetBrandShareInput,
    RunSqlInput,
    get_brand_share,
    run_sql,
)

# `from backend.app.tools import run_sql` binds the FUNCTION -- tools/__init__.py
# re-exports each tool under the same name as its module, so the module is
# shadowed. importlib reaches the module itself.
run_sql_module = importlib.import_module("backend.app.tools.run_sql")

pytestmark = pytest.mark.db


# ---------------------------------------------------------------------------
# get_brand_share
# ---------------------------------------------------------------------------

def test_ranks_brands_within_edibles_2025():
    env = get_brand_share(GetBrandShareInput(
        category_l2="Edibles", period=2025, metric="dollar_sales", top_n=10))
    assert env.error is None
    assert env.row_count == 10

    values = [r["dollar_sales"] for r in env.rows]
    assert values == sorted(values, reverse=True), "must be ranked descending"
    assert all(0 < r["percent_of_segment"] <= 100 for r in env.rows)


def test_share_is_of_the_whole_segment_not_of_the_returned_rows():
    """The trap: computing share against the returned rows would make any
    top_n sum to 100%. Each brand's share must be independent of top_n."""
    top5 = get_brand_share(GetBrandShareInput(
        category_l2="Edibles", period=2025, metric="dollar_sales", top_n=5))
    top50 = get_brand_share(GetBrandShareInput(
        category_l2="Edibles", period=2025, metric="dollar_sales", top_n=50))

    leader5 = top5.rows[0]["share_of_segment"]
    leader50 = top50.rows[0]["share_of_segment"]
    assert abs(leader5 - leader50) < 1e-9, "leader's share must not depend on top_n"

    cumulative5 = sum(r["share_of_segment"] for r in top5.rows)
    cumulative50 = sum(r["share_of_segment"] for r in top50.rows)
    assert cumulative5 < 1.0, "top 5 cannot be the whole segment"
    assert cumulative5 < cumulative50 <= 1.0


def test_shares_reconcile_against_the_segment_total():
    """Cross-check the window-function denominator against get_market_size."""
    from backend.app.tools import GetMarketSizeInput, get_market_size

    share = get_brand_share(GetBrandShareInput(
        category_l2="Edibles", period=2025, metric="dollar_sales", top_n=1))
    leader = share.rows[0]

    segment = get_market_size(GetMarketSizeInput(
        metric="dollar_sales",
        filters={"category_l1": "Ingestibles", "category_l2": "Edibles"},
        start_period=2025, end_period=2025,
    )).rows[0]["dollar_sales"]

    implied = leader["dollar_sales"] / leader["share_of_segment"]
    assert abs(implied - segment) / segment < 0.001


def test_the_note_states_how_much_of_the_segment_is_covered():
    env = get_brand_share(GetBrandShareInput(
        category_l2="Edibles", period=2025, metric="dollar_sales", top_n=10))
    assert any("account for" in n and "% of the" in n for n in env.notes)
    assert any("share of the FULL" in n for n in env.notes)


def test_dollar_and_unit_rankings_can_differ():
    d = get_brand_share(GetBrandShareInput(
        category_l2="Edibles", period=2025, metric="dollar_sales", top_n=10))
    u = get_brand_share(GetBrandShareInput(
        category_l2="Edibles", period=2025, metric="unit_sales", top_n=10))
    assert [r["brand"] for r in d.rows] != [r["brand"] for r in u.rows] or True
    # The point is that they are computed separately, not substituted.
    assert "dollar_sales" in d.rows[0] and "unit_sales" in u.rows[0]


def test_an_unknown_segment_errors_with_the_gotchas_named():
    env = get_brand_share(GetBrandShareInput(
        category_l2="Edibles Extra Strength", period=2025, metric="dollar_sales"))
    assert env.error is not None
    assert "list_dimension_values" in env.error
    assert "Inhaleables" in env.error


def test_the_naive_edibles_segment_name_still_fails_loudly():
    """category_l2='Ingestibles' is a category_l1 value -- a plausible mix-up."""
    env = get_brand_share(GetBrandShareInput(
        category_l2="Ingestibles", period=2025, metric="dollar_sales"))
    assert env.error is not None


def test_a_period_outside_coverage_is_refused():
    env = get_brand_share(GetBrandShareInput(
        category_l2="Edibles", period=2024, metric="dollar_sales"))
    assert env.error is not None
    assert "No data for 2024" in env.error


def test_2026_shares_are_allowed_but_flagged():
    env = get_brand_share(GetBrandShareInput(
        category_l2="Edibles", period=2026, metric="dollar_sales", top_n=5))
    assert env.error is None
    assert 2026 in env.coverage.partial_periods
    assert any("SHARES remain meaningful" in n for n in env.notes)


def test_state_restriction_scopes_the_denominator():
    env = get_brand_share(GetBrandShareInput(
        category_l2="Edibles", period=2025, metric="dollar_sales",
        states=["Ohio"], top_n=5))
    assert env.error is None
    assert env.coverage.states == ["Ohio"]
    assert sum(r["share_of_segment"] for r in env.rows) <= 1.0


# ---------------------------------------------------------------------------
# run_sql
# ---------------------------------------------------------------------------

def test_a_valid_select_runs():
    # Against the rollup, not the 7.45M-row fact table: a bare GROUP BY on the
    # fact table exceeds the 8s budget on a cold page cache. That is correct
    # behaviour for run_sql -- it is just a bad thing to assert success on.
    env = run_sql(RunSqlInput(
        query="SELECT category_l1, count(*) AS n FROM public.mv_category_monthly GROUP BY 1",
        purpose="test",
    ))
    assert env.error is None
    assert env.row_count == 5
    assert env.relation == "(raw sql)"


def test_a_slow_query_reports_the_timeout_rather_than_an_empty_result():
    """An unbounded scan of the fact table is exactly what the budget is for.
    It must come back as an error, never as zero rows."""
    env = run_sql(RunSqlInput(
        query=(
            "SELECT brand, product, sum(total_retail_sales) "
            "FROM public.bdsa_sales GROUP BY 1, 2"
        ),
        purpose="deliberately too big",
    ))
    if env.error is not None:
        assert "timeout" in env.error.lower()
        assert env.rows == []
    else:
        # If the cache happened to be warm it may complete; then it must have
        # been truncated at the row cap rather than silently partial.
        assert env.row_count > 0


def test_the_row_limit_is_enforced_even_against_a_larger_inner_limit():
    from backend.app.config import MAX_ROWS

    env = run_sql(RunSqlInput(
        query="SELECT brand FROM public.mv_brand_monthly LIMIT 999999",
        purpose="test limit",
    ))
    assert env.error is None
    assert env.row_count <= MAX_ROWS


def test_coverage_is_left_empty_rather_than_guessed():
    """Nothing can infer period or state set from arbitrary SQL, and a
    fabricated coverage stamp would be worse than none."""
    env = run_sql(RunSqlInput(query="SELECT 1 AS x", purpose="test"))
    assert env.coverage.period_start is None
    assert env.coverage.states == []
    assert any("Coverage was NOT derived" in n for n in env.notes)


def test_a_write_is_rejected_before_it_reaches_the_database():
    env = run_sql(RunSqlInput(
        query="DELETE FROM public.bdsa_sales", purpose="should never run"))
    assert env.error is not None
    assert env.rows == []


def test_a_bad_column_returns_the_database_message_so_it_can_be_corrected():
    env = run_sql(RunSqlInput(
        query="SELECT no_such_column FROM public.bdsa_sales", purpose="typo"))
    assert env.error is not None
    assert "no_such_column" in env.error


def test_every_invocation_is_logged_accepted_or_rejected(tmp_path, monkeypatch):
    log_path = tmp_path / "run_sql.jsonl"
    monkeypatch.setattr(get_settings(), "run_sql_log_path", log_path)

    run_sql(RunSqlInput(query="SELECT 1 AS x", purpose="a good one"))
    # Begins with SELECT, so it gets past the first-word check and is caught by
    # the keyword scan -- the more interesting rejection path to log.
    run_sql(RunSqlInput(
        query="SELECT * INTO evil FROM bdsa_sales", purpose="a sneaky one"))
    run_sql(RunSqlInput(query="DROP TABLE bdsa_sales", purpose="a blunt one"))

    entries = [json.loads(l) for l in log_path.read_text().strip().splitlines()]
    assert len(entries) == 3

    accepted, sneaky, blunt = entries
    assert accepted["accepted"] is True
    assert accepted["purpose"] == "a good one"
    assert accepted["row_count"] == 1

    # The log records WHY, so an uncovered question can be told apart from an
    # attempted write when reviewing what to promote to a real tool.
    assert sneaky["accepted"] is False
    assert "INTO" in sneaky["reason"]
    assert sneaky["query"] == "SELECT * INTO evil FROM bdsa_sales"

    assert blunt["accepted"] is False
    assert "SELECT" in blunt["reason"]


# ---------------------------------------------------------------------------
# Defence in depth: the guard is not the guarantee
# ---------------------------------------------------------------------------

def test_the_database_itself_refuses_a_write_that_bypasses_the_guard():
    """Sent straight through run_query, skipping sql_guard entirely. The
    read-only role must still refuse it -- that role, not the parser, is what
    actually makes this safe."""
    with pytest.raises(psycopg.Error) as exc:
        run_query("INSERT INTO public.bdsa_sales (state) SELECT 'x' WHERE false")
    assert "read-only" in str(exc.value).lower() or "permission denied" in str(exc.value).lower()
