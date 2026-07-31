#!/usr/bin/env python3
"""
load_states.py
Load a cleaned BDSA extract into public.bdsa_sales, replacing exactly the
(state, period_year) combinations the extract contains and nothing else.

Runs entirely inside ONE transaction:

    stage -> delete matching (state, year) -> insert -> verify -> commit

Defaults to a DRY RUN that rolls back, printing exactly what would change.
Pass --commit to make it real.

Why (state, period_year) and not state alone: a load may replace some years
for a state while leaving others intact. Loading Arkansas 2025 must not
delete the Arkansas 2026 rows that are already present and not being
replaced. Deleting by state would silently destroy them.

Two gaps between clean_bdsa.py output and the live table are filled in the
staging table before the swap:
  * period_grain -- not produced by the cleaner; 'year' on every existing row
  * source_file  -- points at raw_normalized/; rewritten to the raw_exports/
                    convention used by the rest of the table

Usage:
    python load_states.py --csv ./clean/bdsa_clean.csv            # dry run
    python load_states.py --csv ./clean/bdsa_clean.csv --commit
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from introspect_schema import load_dotenv  # noqa: E402

# The 30 columns clean_bdsa.py emits, in file order. period_grain is absent.
CLEAN_COLUMNS = [
    "period_month", "state", "category_l1", "category_l2", "category_l3",
    "category_l4", "category_l5", "brand", "product", "pack_size",
    "infusion_type", "phenotype", "strain", "is_live_extract", "mood_effect",
    "cannabinoid_mix", "sugar_free", "fast_acting", "flavor",
    "total_item_weight", "items_per_pack", "pct_thc_potency", "total_thc_mg",
    "total_cbd_mg", "total_retail_sales", "total_units", "original_list_price",
    "source_file", "period_year", "is_suppressed",
]


def report(cur, states: list[str], label: str) -> None:
    cur.execute(
        """
        SELECT state, period_year, count(*), sum(total_retail_sales),
               sum(total_units), count(DISTINCT source_file)
        FROM public.bdsa_sales WHERE state = ANY(%s)
        GROUP BY 1,2 ORDER BY 1,2
        """,
        (states,),
    )
    rows = cur.fetchall()
    print(f"  {label}")
    if not rows:
        print("      (none)")
    for st, yr, n, sales, units, files in rows:
        print(f"      {st:<12} {yr}  {n:>9,} rows  ${float(sales):>16,.2f}  "
              f"{float(units):>14,.2f} units  {files} file(s)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--commit", action="store_true", help="Actually commit (default: roll back)")
    ap.add_argument("--refresh-views", action="store_true",
                    help="REFRESH the materialized views after a successful commit")
    args = ap.parse_args()

    csv_path = Path(args.csv).resolve()
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found", file=sys.stderr)
        return 2

    load_dotenv(REPO_ROOT / ".env")
    dsn = os.environ.get("NEON_INTROSPECT_URL") or os.environ.get("NEON_READONLY_URL")
    if not dsn:
        print("ERROR: no connection string in .env", file=sys.stderr)
        return 2

    print(f"=== load_states.py -- {'COMMIT' if args.commit else 'DRY RUN (will roll back)'} ===\n")
    print(f"source: {csv_path}\n")
    collist = ", ".join(CLEAN_COLUMNS)

    with psycopg.connect(dsn) as conn:  # transactional; no autocommit
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 900000")

            # 1. Stage
            cur.execute(
                "CREATE TEMP TABLE incoming (LIKE public.bdsa_sales INCLUDING DEFAULTS) "
                "ON COMMIT DROP"
            )
            with open(csv_path, "r", encoding="utf-8", newline="") as f:
                with cur.copy(
                    f"COPY incoming ({collist}) FROM STDIN WITH (FORMAT CSV, HEADER true)"
                ) as cp:
                    while chunk := f.read(1 << 20):
                        cp.write(chunk)
            cur.execute("SELECT count(*) FROM incoming")
            print(f"staged {cur.fetchone()[0]:,} rows")

            # 2. Fill the gaps the cleaner does not produce.
            #
            # period_grain is DERIVED, not assumed. An annual bucket is always
            # a single January-1 date; anything else -- more than one distinct
            # period_month for a (source_file, state, year), or a month that
            # is not January -- came from a month-grain export. Hardcoding
            # 'year' here would mislabel monthly rows, and every downstream
            # coverage statement would inherit the lie.
            cur.execute("""
                UPDATE incoming t SET period_grain = g.grain
                FROM (
                    SELECT source_file, state, period_year,
                           CASE WHEN count(DISTINCT period_month) > 1
                                  OR max(EXTRACT(MONTH FROM period_month)) <> 1
                                THEN 'month' ELSE 'year' END AS grain
                    FROM incoming GROUP BY 1,2,3
                ) g
                WHERE t.source_file = g.source_file AND t.state = g.state
                  AND t.period_year = g.period_year
            """)
            cur.execute("""
                SELECT state, period_year, period_grain,
                       count(DISTINCT period_month) AS months, count(*) AS rows
                FROM incoming GROUP BY 1,2,3 ORDER BY 1,2
            """)
            print("\n  derived grain per (state, year):")
            for st, yr, grain, months, n in cur.fetchall():
                print(f"      {st:<14} {yr}  grain={grain:<6} {months:>2} distinct month(s)  {n:>8,} rows")
            cur.execute(
                "UPDATE incoming SET source_file = "
                "replace(source_file, 'raw_normalized/', 'raw_exports/')"
            )

            # 3. Guards -- refuse to touch anything if the staged data is malformed
            cur.execute(
                "SELECT count(*) FROM incoming WHERE state IS NULL "
                "OR period_year IS NULL OR period_month IS NULL OR period_grain IS NULL"
            )
            bad = cur.fetchone()[0]
            if bad:
                print(f"ABORT: {bad} staged rows have a NULL key field", file=sys.stderr)
                conn.rollback()
                return 1

            # A single source_file spanning multiple years means the export
            # was mislabelled -- exactly the Maine failure. Written as an
            # aggregate, not a correlated subquery: the temp table has no
            # indexes, so EXISTS(...) over it is O(n^2) and times out.
            cur.execute(
                "SELECT source_file, count(DISTINCT period_year) AS years "
                "FROM incoming GROUP BY 1 HAVING count(DISTINCT period_year) > 1"
            )
            straddling = cur.fetchall()
            if straddling:
                print("ABORT: source_file(s) span multiple years -- inspect before loading:",
                      file=sys.stderr)
                for sf, n in straddling:
                    print(f"  {sf}: {n} years", file=sys.stderr)
                conn.rollback()
                return 1

            # 4. What are we replacing?
            cur.execute("SELECT DISTINCT state, period_year FROM incoming ORDER BY 1,2")
            pairs = cur.fetchall()
            states = sorted({p[0] for p in pairs})
            print(f"\nincoming (state, year) combinations: "
                  f"{', '.join(f'{s}/{y}' for s, y in pairs)}\n")

            print("BEFORE:")
            report(cur, states, "affected states in bdsa_sales:")
            cur.execute("SELECT count(*) FROM public.bdsa_sales")
            total_before = cur.fetchone()[0]
            print(f"      whole table: {total_before:,} rows\n")

            # 5. Swap -- delete ONLY the (state, year) pairs being replaced
            cur.execute(
                "DELETE FROM public.bdsa_sales t USING (SELECT DISTINCT state, period_year "
                "FROM incoming) i WHERE t.state = i.state AND t.period_year = i.period_year"
            )
            deleted = cur.rowcount
            cur.execute(
                f"INSERT INTO public.bdsa_sales ({collist}, period_grain) "
                f"SELECT {collist}, period_grain FROM incoming"
            )
            inserted = cur.rowcount
            print(f"deleted {deleted:,} rows, inserted {inserted:,}\n")

            # 6. Verify inside the transaction
            print("AFTER:")
            report(cur, states, "affected states in bdsa_sales:")
            cur.execute("SELECT count(*) FROM public.bdsa_sales")
            print(f"      whole table: {cur.fetchone()[0]:,} rows")

            cur.execute("""
                SELECT period_year, count(DISTINCT state), count(*), sum(total_retail_sales)
                FROM public.bdsa_sales GROUP BY 1 ORDER BY 1
            """)
            print("\n  national totals by year:")
            for yr, st_n, n, sales in cur.fetchall():
                print(f"      {yr}: {st_n} states  {n:>10,} rows  ${float(sales):>18,.2f}")

            cur.execute("SELECT count(*) FROM public.bdsa_sales "
                        "WHERE category_l2='Edibles' AND fast_acting IS NULL")
            print(f"\n  edibles rows with NULL fast_acting (must be 0): {cur.fetchone()[0]}")
            cur.execute("SELECT DISTINCT period_grain FROM public.bdsa_sales")
            print(f"  distinct period_grain: {[r[0] for r in cur.fetchall()]}")
            cur.execute("""
                SELECT state FROM public.bdsa_sales GROUP BY state
                HAVING NOT (bool_or(period_year=2025) AND bool_or(period_year=2026))
                ORDER BY 1
            """)
            missing = [r[0] for r in cur.fetchall()]
            print(f"  states still missing a year: {missing if missing else 'none'}")

            if args.commit:
                conn.commit()
                print("\nCOMMITTED.")
            else:
                conn.rollback()
                print("\nROLLED BACK -- nothing changed. Re-run with --commit to apply.")
                return 0

    if args.commit and args.refresh_views:
        print("\nRefreshing materialized views (ACCESS EXCLUSIVE lock)...")
        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = 1800000")
                for mv in ("public.mv_brand_monthly", "public.mv_category_monthly"):
                    cur.execute(f"REFRESH MATERIALIZED VIEW {mv}")
                    print(f"  refreshed {mv}")
    elif args.commit:
        print("\nNOTE: materialized views are STALE. Refresh them before querying.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
