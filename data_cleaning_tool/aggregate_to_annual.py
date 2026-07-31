#!/usr/bin/env python3
"""
aggregate_to_annual.py
Collapse any month-grain rows in a cleaned BDSA extract to annual buckets,
so every state in bdsa_sales carries the same grain.

BDSA names its first column after the export grain: "Year" for annual pulls,
"Month" for monthly ones. A monthly export carries the same schema but ~12x
the rows. Loading it as-is would leave one state at month grain and the rest
at year grain -- sums by period_year stay correct, but nothing else does.

This step groups on every non-additive column and sums only the two measures,
so the annual total is exact by construction. Rows already at year grain pass
through untouched.

is_suppressed is RECOMPUTED on the annual totals rather than inherited: a
single slow month can fall under the revenue-per-unit floor while the year
does not. Inheriting the monthly flag would suppress rows that belong in the
data.

Usage:
    python aggregate_to_annual.py --input ./clean/bdsa_clean.parquet \
                                  --output ./clean/bdsa_annual.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

# Matches SUPPRESSION_PRICE_THRESHOLD in clean_bdsa.py. Kept in sync by hand;
# if that constant moves, this must move with it.
SUPPRESSION_PRICE_THRESHOLD = 0.25

# Every column except period_month (recomputed), the two summed measures, and
# is_suppressed (recomputed). These are product//attribute columns that do not
# vary within a year for a given SKU row.
GROUP_COLUMNS = [
    "state", "category_l1", "category_l2", "category_l3", "category_l4",
    "category_l5", "brand", "product", "pack_size", "infusion_type",
    "phenotype", "strain", "is_live_extract", "mood_effect",
    "cannabinoid_mix", "sugar_free", "fast_acting", "flavor",
    "total_item_weight", "items_per_pack", "pct_thc_potency", "total_thc_mg",
    "total_cbd_mg", "original_list_price", "source_file", "period_year",
]

# The exact column order clean_bdsa.py emits, which the loader depends on.
OUTPUT_COLUMNS = [
    "period_month", "state", "category_l1", "category_l2", "category_l3",
    "category_l4", "category_l5", "brand", "product", "pack_size",
    "infusion_type", "phenotype", "strain", "is_live_extract", "mood_effect",
    "cannabinoid_mix", "sugar_free", "fast_acting", "flavor",
    "total_item_weight", "items_per_pack", "pct_thc_potency", "total_thc_mg",
    "total_cbd_mg", "total_retail_sales", "total_units", "original_list_price",
    "source_file", "period_year", "is_suppressed",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Cleaned parquet or CSV from clean_bdsa.py")
    ap.add_argument("--output", required=True, help="Annual-grain CSV for the loader")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"ERROR: {src} not found", file=sys.stderr)
        return 2
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute("PRAGMA threads=4;")
    reader = (f"read_parquet('{src.as_posix()}')" if src.suffix == ".parquet"
              else f"read_csv('{src.as_posix()}', header=true, sample_size=-1)")
    con.execute(f"CREATE VIEW src AS SELECT * FROM {reader};")

    # Identify which (source_file, state, period_year) groups are month grain.
    con.execute("""
        CREATE TABLE grain AS
        SELECT source_file, state, period_year,
               CASE WHEN COUNT(DISTINCT period_month) > 1
                      OR MAX(EXTRACT(month FROM period_month)) <> 1
                    THEN 'month' ELSE 'year' END AS grain,
               COUNT(DISTINCT period_month) AS months,
               COUNT(*) AS rows,
               SUM(total_retail_sales) AS sales,
               SUM(total_units) AS units
        FROM src GROUP BY 1,2,3;
    """)

    print("Input grain by (state, year):")
    for st, yr, g, m, n, sales, units in con.execute("""
        SELECT state, period_year, grain, months, rows, sales, units
        FROM grain ORDER BY state, period_year
    """).fetchall():
        print(f"  {st:<14} {yr}  grain={g:<6} {m:>2} month(s)  {n:>8,} rows  ${sales:>16,.2f}")

    monthly = con.execute("SELECT COUNT(*) FROM grain WHERE grain='month'").fetchone()[0]
    if not monthly:
        print("\nNothing at month grain -- copying through unchanged.")

    group_list = ", ".join(GROUP_COLUMNS)
    con.execute(f"""
        CREATE TABLE final AS
        WITH tagged AS (
            SELECT s.*, g.grain
            FROM src s JOIN grain g
              ON s.source_file = g.source_file AND s.state = g.state
             AND s.period_year = g.period_year
        ),
        rolled AS (
            SELECT
                make_date(period_year, 1, 1) AS period_month,
                {group_list},
                SUM(total_retail_sales) AS total_retail_sales,
                SUM(total_units) AS total_units
            FROM tagged WHERE grain = 'month'
            GROUP BY period_year, {group_list}
        ),
        rolled_flagged AS (
            SELECT period_month, {group_list}, total_retail_sales, total_units,
                   CASE
                     WHEN total_retail_sales IS NULL OR total_units IS NULL
                          OR total_units = 0 THEN FALSE
                     WHEN total_retail_sales / total_units
                          < {SUPPRESSION_PRICE_THRESHOLD} THEN TRUE
                     ELSE FALSE
                   END AS is_suppressed
            FROM rolled
        ),
        passthrough AS (
            SELECT period_month, {group_list}, total_retail_sales, total_units,
                   is_suppressed
            FROM tagged WHERE grain = 'year'
        )
        SELECT * FROM rolled_flagged
        UNION ALL
        SELECT * FROM passthrough;
    """)

    # The whole point: dollars and units must survive aggregation exactly.
    before = con.execute("SELECT COUNT(*), SUM(total_retail_sales), SUM(total_units) FROM src").fetchone()
    after = con.execute("SELECT COUNT(*), SUM(total_retail_sales), SUM(total_units) FROM final").fetchone()
    print(f"\nrows   {before[0]:>10,}  ->  {after[0]:>10,}   ({before[0]-after[0]:,} collapsed)")
    print(f"sales  ${before[1]:>18,.2f}  ->  ${after[1]:>18,.2f}")
    print(f"units  {before[2]:>19,.2f}  ->  {after[2]:>19,.2f}")

    ok = True
    if round(before[1], 2) != round(after[1], 2):
        print(f"FAIL: dollar total changed by {after[1]-before[1]:,.4f}", file=sys.stderr)
        ok = False
    if round(before[2], 2) != round(after[2], 2):
        print(f"FAIL: unit total changed by {after[2]-before[2]:,.4f}", file=sys.stderr)
        ok = False
    if not ok:
        return 1
    print("OK: dollar and unit totals preserved exactly.")

    print("\nOutput grain by (state, year):")
    for st, yr, m, n, sales in con.execute("""
        SELECT state, period_year, COUNT(DISTINCT period_month), COUNT(*),
               SUM(total_retail_sales)
        FROM final GROUP BY 1,2 ORDER BY 1,2
    """).fetchall():
        print(f"  {st:<14} {yr}  {m} month bucket(s)  {n:>8,} rows  ${sales:>16,.2f}")

    con.execute(
        f"COPY (SELECT {', '.join(OUTPUT_COLUMNS)} FROM final) "
        f"TO '{out.as_posix()}' (FORMAT CSV, HEADER, DELIMITER ',');"
    )
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
