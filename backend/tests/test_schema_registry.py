"""The hardcoded registry must match the live database.

schema_registry.py hardcodes which columns live in which relation so routing is
predictable and the agent cannot reach a column that does not exist. Hardcoding
is only safe if drift fails loudly, which is what these tests are for.
"""

from __future__ import annotations

import pytest

from backend.app.db import run_query
from backend.app.schema_registry import (
    FACT,
    MV_BRAND,
    MV_CATEGORY,
    RELATIONS,
    choose_relation,
    metric_column,
)

pytestmark = pytest.mark.db


def _live_columns(relation: str) -> set[str]:
    res = run_query(
        """
        SELECT a.attname AS name
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = %(rel)s
          AND a.attnum > 0 AND NOT a.attisdropped
        """,
        {"rel": relation},
    )
    return {r["name"] for r in res.rows}


@pytest.mark.parametrize("relation", [FACT, MV_BRAND, MV_CATEGORY])
def test_declared_dimensions_exist_in_the_database(relation):
    live = _live_columns(relation)
    assert live, f"{relation} does not exist"
    declared = RELATIONS[relation].dimensions
    missing = declared - live
    assert not missing, f"{relation}: registry names columns that do not exist: {sorted(missing)}"


@pytest.mark.parametrize("relation", [FACT, MV_BRAND, MV_CATEGORY])
def test_declared_metric_columns_exist(relation):
    live = _live_columns(relation)
    rel = RELATIONS[relation]
    assert rel.dollars in live
    assert rel.units in live


def test_metric_vocabulary_maps_to_real_columns():
    """The agent says dollar_sales; the database says something different in
    each relation. The mapping is the only place that inconsistency lives."""
    assert metric_column(FACT, "dollar_sales") == "total_retail_sales"
    assert metric_column(MV_CATEGORY, "dollar_sales") == "total_sales"
    assert metric_column(MV_BRAND, "dollar_sales") == "total_sales"
    assert metric_column(FACT, "unit_sales") == "total_units"
    with pytest.raises(ValueError):
        metric_column(FACT, "revenue")


def test_routing_prefers_the_cheapest_relation():
    assert choose_relation({"state", "period_year"}).name == MV_CATEGORY
    assert choose_relation({"brand", "period_year"}).name == MV_BRAND
    # product exists only on the fact table
    assert choose_relation({"product"}).name == FACT


def test_routing_rejects_unknown_dimensions():
    with pytest.raises(ValueError, match="unknown dimension"):
        choose_relation({"nonexistent_column"})


def test_views_exclude_suppressed_and_reconcile_to_the_fact_table():
    """Proves the views are not stale AND that they net out suppression.

    This is the check that catches a data load where the views were not
    refreshed -- the failure mode that would otherwise serve last month's
    numbers with total confidence.
    """
    fact = run_query(
        "SELECT sum(total_retail_sales) AS d, sum(total_units) AS u "
        "FROM public.bdsa_sales WHERE NOT is_suppressed"
    ).rows[0]
    brand = run_query(
        f"SELECT sum(total_sales) AS d, sum(total_units) AS u FROM public.{MV_BRAND}"
    ).rows[0]
    category = run_query(
        f"SELECT sum(total_sales) AS d, sum(total_units) AS u FROM public.{MV_CATEGORY}"
    ).rows[0]

    assert round(float(fact["d"]), 2) == round(float(brand["d"]), 2) == round(float(category["d"]), 2)
    assert round(float(fact["u"]), 2) == round(float(brand["u"]), 2) == round(float(category["u"]), 2)
