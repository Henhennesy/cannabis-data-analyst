"""What columns exist, where they live, and which relation to query.

Hardcoded on purpose: the agent must not be able to reach a column that does
not exist, and the routing has to be predictable. `tests/test_schema_registry.py`
asserts every statement here against the live database, so drift fails a test
rather than surfacing as a wrong number.

Routing exists because it is the difference between fitting the 8s statement
timeout and not. Summing total_retail_sales by year over the 7.45M-row fact
table takes 9.19s; the same answer from mv_category_monthly takes 0.12s.
"""

from __future__ import annotations

from dataclasses import dataclass

FACT = "bdsa_sales"
MV_BRAND = "mv_brand_monthly"
MV_CATEGORY = "mv_category_monthly"


@dataclass(frozen=True)
class Relation:
    name: str
    dimensions: frozenset[str]
    dollars: str          # column holding retail dollars
    units: str            # column holding units
    excludes_suppressed: bool
    approx_rows: int      # for cost ordering only


# The two views are GROUP BY rollups of the fact table with
# `WHERE NOT is_suppressed` baked in. Verified to reconcile to the cent
# against the fact table net of suppression -- see reports/baseline_metrics.md.
RELATIONS: dict[str, Relation] = {
    MV_CATEGORY: Relation(
        name=MV_CATEGORY,
        dimensions=frozenset({
            "state", "category_l1", "category_l2", "category_l3",
            "fast_acting", "mood_effect", "cannabinoid_mix", "sugar_free",
            "period_grain", "period_month", "period_year",
        }),
        dollars="total_sales",
        units="total_units",
        excludes_suppressed=True,
        approx_rows=12_255,
    ),
    MV_BRAND: Relation(
        name=MV_BRAND,
        dimensions=frozenset({
            "state", "category_l1", "category_l2", "category_l3", "brand",
            "fast_acting", "mood_effect", "cannabinoid_mix", "sugar_free",
            "period_grain", "period_month", "period_year",
        }),
        dollars="total_sales",
        units="total_units",
        excludes_suppressed=True,
        approx_rows=189_983,
    ),
    FACT: Relation(
        name=FACT,
        dimensions=frozenset({
            "state", "category_l1", "category_l2", "category_l3",
            "category_l4", "category_l5", "brand", "product", "pack_size",
            "infusion_type", "phenotype", "strain", "is_live_extract",
            "mood_effect", "cannabinoid_mix", "sugar_free", "fast_acting",
            "flavor", "total_item_weight", "source_file", "period_year",
            "period_month", "period_grain", "is_suppressed",
        }),
        dollars="total_retail_sales",
        units="total_units",
        excludes_suppressed=False,
        approx_rows=7_450_435,
    ),
}

# Cheapest first.
ROUTING_ORDER = [MV_CATEGORY, MV_BRAND, FACT]

# Every dimension the agent may name, anywhere.
ALL_DIMENSIONS: frozenset[str] = frozenset().union(
    *(r.dimensions for r in RELATIONS.values())
)

# The vocabulary the agent uses, mapped to real columns per relation. The
# brief says `dollar_sales` / `unit_sales`; the database says
# `total_retail_sales` / `total_units`, and the views rename the former to
# `total_sales`. The agent never sees that inconsistency.
METRICS = {"dollar_sales", "unit_sales"}


def metric_column(relation: str, metric: str) -> str:
    if metric not in METRICS:
        raise ValueError(f"unknown metric {metric!r}; expected one of {sorted(METRICS)}")
    rel = RELATIONS[relation]
    return rel.dollars if metric == "dollar_sales" else rel.units


def choose_relation(needed: set[str], *, require_fact: bool = False) -> Relation:
    """Cheapest relation carrying every column named.

    `require_fact` forces the fact table for questions that must see
    suppressed rows or per-SKU columns.
    """
    unknown = needed - ALL_DIMENSIONS
    if unknown:
        raise ValueError(
            f"unknown dimension(s): {sorted(unknown)}. "
            f"Valid dimensions: {sorted(ALL_DIMENSIONS)}"
        )
    if require_fact:
        return RELATIONS[FACT]
    for name in ROUTING_ORDER:
        rel = RELATIONS[name]
        if needed <= rel.dimensions:
            return rel
    return RELATIONS[FACT]


# Dimensions with too many distinct values to enumerate from the fact table
# inside the statement timeout. Measured warm against the live database:
#
#   product  73.19s, 3,415,726 distinct  -- impossible, and far past MAX_ROWS
#   strain    5.79s,   202,264 distinct  -- fits, but only just, and truncates
#   brand     0.32s,    13,785 distinct  -- via mv_brand_monthly, fine
#
# Listing these unfiltered is refused with an explanation rather than attempted
# and timed out. A timeout tells the agent nothing; a refusal tells it what to
# do instead.
REQUIRES_NARROWING = frozenset({"product"})

# Enumerable from the fact table but slow enough to warrant routing care.
SLOW_ON_FACT = frozenset({"strain", "product"})
