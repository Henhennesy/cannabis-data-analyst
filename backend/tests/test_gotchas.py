"""The known data traps, asserted against the live database.

Each of these has produced a wrong answer in real analytical work. They are
encoded as tests rather than prompt text because prompt text is advisory and a
failing test is not.
"""

from __future__ import annotations

import pytest

from backend.app.db import run_query

pytestmark = pytest.mark.db


def test_edibles_are_not_a_top_level_category():
    """`category_l1 = 'Edibles'` matches nothing. The naive query returns zero."""
    res = run_query(
        "SELECT count(*) AS n FROM public.bdsa_sales WHERE category_l1 = %(v)s",
        {"v": "Edibles"},
    )
    assert res.rows[0]["n"] == 0


def test_edibles_live_under_ingestibles():
    """The correct path is category_l1='Ingestibles' AND category_l2='Edibles'."""
    res = run_query(
        """
        SELECT count(*) AS n FROM public.bdsa_sales
        WHERE category_l1 = %(l1)s AND category_l2 = %(l2)s
        """,
        {"l1": "Ingestibles", "l2": "Edibles"},
    )
    assert res.rows[0]["n"] > 0


def test_inhaleables_spelling():
    """It is 'Inhaleables'. The natural spelling 'Inhalables' matches nothing."""
    wrong = run_query(
        "SELECT count(*) AS n FROM public.bdsa_sales WHERE category_l1 = %(v)s",
        {"v": "Inhalables"},
    )
    right = run_query(
        "SELECT count(*) AS n FROM public.bdsa_sales WHERE category_l1 = %(v)s",
        {"v": "Inhaleables"},
    )
    assert wrong.rows[0]["n"] == 0
    assert right.rows[0]["n"] > 0


def test_fast_acting_has_exactly_two_non_null_values():
    """Scoped to the indexed category predicate on purpose.

    The unqualified `SELECT DISTINCT fast_acting FROM bdsa_sales` is a full
    scan of 7.45M rows with no index on that column. Warm it takes ~1s, but
    cold it pulls every page from Neon's page server and blows the 8s timeout,
    which made this test intermittently fail. Restricting to Ingestibles/Edibles
    uses idx_sales_category (0.20s) and asserts exactly the same thing, since
    test_fast_acting_is_non_null_iff_edibles independently proves no value
    exists outside that path.
    """
    res = run_query(
        """
        SELECT DISTINCT fast_acting FROM public.bdsa_sales
        WHERE category_l1 = %(l1)s AND category_l2 = %(l2)s
        ORDER BY 1
        """,
        {"l1": "Ingestibles", "l2": "Edibles"},
    )
    assert [r["fast_acting"] for r in res.rows] == ["Fast Acting", "Not Fast Acting"]


def test_fast_acting_is_non_null_iff_edibles():
    """The corrected gotcha.

    The original brief said fast_acting holds two literals and "not nulls".
    It is in fact NULL on ~96% of the table -- it is populated if and only if
    category_l2 = 'Edibles'. Stated as a biconditional this catches both a
    null sneaking into a denominator and a value leaking onto a non-edible row.
    """
    res = run_query(
        """
        SELECT count(*) AS violations FROM public.bdsa_sales
        WHERE (fast_acting IS NOT NULL) <> (category_l2 = %(l2)s)
        """,
        {"l2": "Edibles"},
        # No index can serve this predicate -- it is a full scan of 7.45M rows
        # by construction. ~2s warm, but it exceeds the 8s session budget on a
        # cold page cache. This is a data-integrity check, not a user query, so
        # it gets its own budget rather than being weakened into something an
        # index can answer.
        timeout_ms=60_000,
    )
    assert res.rows[0]["violations"] == 0


def test_fast_acting_is_mostly_null_overall():
    """Guards the assumption directly: most of the table has no fast_acting."""
    res = run_query(
        """
        SELECT count(*) FILTER (WHERE fast_acting IS NULL) AS nulls,
               count(*) AS total
        FROM public.bdsa_sales
        """
    )
    row = res.rows[0]
    assert row["nulls"] / row["total"] > 0.9


def test_dollars_and_units_are_different_questions():
    """Fast-acting share differs materially by metric; never substitute one."""
    res = run_query(
        """
        SELECT sum(total_retail_sales) FILTER (WHERE fast_acting = 'Fast Acting')
                 / NULLIF(sum(total_retail_sales), 0) AS dollar_share,
               sum(total_units) FILTER (WHERE fast_acting = 'Fast Acting')
                 / NULLIF(sum(total_units), 0)        AS unit_share
        FROM public.bdsa_sales
        WHERE category_l1 = 'Ingestibles' AND category_l2 = 'Edibles'
          AND period_year = 2025 AND is_suppressed = false
        """
    )
    row = res.rows[0]
    assert abs(float(row["dollar_share"]) - float(row["unit_share"])) > 0.01


def test_period_grain_is_uniformly_year():
    """Mixed grain would make period_month incoherent across states."""
    res = run_query("SELECT DISTINCT period_grain FROM public.bdsa_sales")
    assert [r["period_grain"] for r in res.rows] == ["year"]


def test_period_month_is_a_year_marker_not_a_month():
    """Every period_month is 1 January. There is no sub-annual detail."""
    res = run_query(
        "SELECT count(*) AS n FROM public.bdsa_sales "
        "WHERE EXTRACT(MONTH FROM period_month) <> 1"
    )
    assert res.rows[0]["n"] == 0
