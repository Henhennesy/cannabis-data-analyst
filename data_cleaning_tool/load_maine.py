#!/usr/bin/env python3
"""
load_maine.py
Replace every Maine row in public.bdsa_sales with a freshly cleaned load.

Runs entirely inside ONE transaction:

    stage -> delete Maine -> insert -> verify -> commit (or roll back)

so the table is never observably missing Maine and never holds both the old
and new rows at once. Defaults to a DRY RUN that rolls back, printing exactly
what would change. Pass --commit to make it real.

The cleaned CSV is missing two things relative to the live table, both fixed
in the staging table before the swap:
  * period_grain -- not produced by clean_bdsa.py; every existing row is 'year'
  * source_file  -- points at raw_normalized/; rewritten to the raw_exports/
                    convention used by the other 36 states

Usage:
    python load_maine.py --csv ./clean/bdsa_clean.csv            # dry run
    python load_maine.py --csv ./clean/bdsa_clean.csv --commit   # for real
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

TARGET_STATE = "Maine"


def snapshot(cur) -> list[tuple]:
    cur.execute(
        """
        SELECT period_year, count(*), sum(total_retail_sales), sum(total_units),
               count(DISTINCT source_file)
        FROM public.bdsa_sales WHERE state = %s GROUP BY 1 ORDER BY 1
        """,
        (TARGET_STATE,),
    )
    return cur.fetchall()


def show(label: str, rows: list[tuple]) -> None:
    print(f"  {label}")
    if not rows:
        print("      (no rows)")
    for year, n, sales, units, files in rows:
        print(f"      {year}: {n:>9,} rows  ${sales:>18,.2f}  {units:>16,.2f} units  {files} file(s)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Cleaned CSV from clean_bdsa.py")
    ap.add_argument("--commit", action="store_true", help="Actually commit (default: roll back)")
    ap.add_argument("--refresh-views", action="store_true",
                    help="REFRESH the two materialized views after commit")
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

    mode = "COMMIT" if args.commit else "DRY RUN (will roll back)"
    print(f"=== load_maine.py -- {mode} ===\n")
    print(f"source: {csv_path}\n")

    collist = ", ".join(CLEAN_COLUMNS)

    with psycopg.connect(dsn) as conn:  # transactional: no autocommit
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 600000")

            print("BEFORE:")
            before = snapshot(cur)
            show("Maine currently in bdsa_sales:", before)
            cur.execute("SELECT count(*) FROM public.bdsa_sales")
            total_before = cur.fetchone()[0]
            print(f"      whole table: {total_before:,} rows\n")

            # 1. Stage
            cur.execute(
                "CREATE TEMP TABLE me_new (LIKE public.bdsa_sales INCLUDING DEFAULTS) "
                "ON COMMIT DROP"
            )
            with open(csv_path, "r", encoding="utf-8", newline="") as f:
                with cur.copy(
                    f"COPY me_new ({collist}) FROM STDIN WITH (FORMAT CSV, HEADER true)"
                ) as cp:
                    while chunk := f.read(1 << 20):
                        cp.write(chunk)
            cur.execute("SELECT count(*) FROM me_new")
            staged = cur.fetchone()[0]
            print(f"staged {staged:,} rows into temp table")

            # 2. Fill the two gaps
            cur.execute("UPDATE me_new SET period_grain = 'year' WHERE period_grain IS NULL")
            cur.execute(
                "UPDATE me_new SET source_file = replace(source_file, 'raw_normalized/', 'raw_exports/')"
            )
            cur.execute("SELECT DISTINCT source_file FROM me_new ORDER BY 1")
            print("  source_file values after rewrite:")
            for (sf,) in cur.fetchall():
                print(f"      {sf}")

            # 3. Guard: refuse to proceed if the staged data is not what we expect
            cur.execute("SELECT DISTINCT state FROM me_new")
            states = [r[0] for r in cur.fetchall()]
            if states != [TARGET_STATE]:
                print(f"ABORT: staged data covers {states}, expected only ['{TARGET_STATE}']",
                      file=sys.stderr)
                conn.rollback()
                return 1
            cur.execute("SELECT count(*) FROM me_new WHERE period_grain IS NULL "
                        "OR period_month IS NULL OR period_year IS NULL")
            bad = cur.fetchone()[0]
            if bad:
                print(f"ABORT: {bad} staged rows have a NULL period field", file=sys.stderr)
                conn.rollback()
                return 1

            # 4. Swap
            cur.execute("DELETE FROM public.bdsa_sales WHERE state = %s", (TARGET_STATE,))
            deleted = cur.rowcount
            cur.execute(f"INSERT INTO public.bdsa_sales ({collist}, period_grain) "
                        f"SELECT {collist}, period_grain FROM me_new")
            inserted = cur.rowcount
            print(f"\ndeleted {deleted:,} old Maine rows, inserted {inserted:,} new\n")

            # 5. Verify inside the transaction
            print("AFTER:")
            show("Maine in bdsa_sales:", snapshot(cur))
            cur.execute("SELECT count(*) FROM public.bdsa_sales")
            print(f"      whole table: {cur.fetchone()[0]:,} rows")
            cur.execute("""
                SELECT period_year, count(DISTINCT state), sum(total_retail_sales)
                FROM public.bdsa_sales GROUP BY 1 ORDER BY 1
            """)
            print("  national totals by year:")
            for year, states_n, sales in cur.fetchall():
                print(f"      {year}: {states_n} states  ${sales:,.2f}")
            cur.execute("""
                SELECT count(*) FROM public.bdsa_sales
                WHERE category_l2 = 'Edibles' AND fast_acting IS NULL
            """)
            print(f"  edibles rows with NULL fast_acting (must be 0): {cur.fetchone()[0]}")
            cur.execute("SELECT DISTINCT period_grain FROM public.bdsa_sales")
            print(f"  distinct period_grain: {[r[0] for r in cur.fetchall()]}")

            if args.commit:
                conn.commit()
                print("\nCOMMITTED.")
            else:
                conn.rollback()
                print("\nROLLED BACK -- nothing changed. Re-run with --commit to apply.")
                return 0

    if args.commit and args.refresh_views:
        print("\nRefreshing materialized views (takes an ACCESS EXCLUSIVE lock)...")
        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = 900000")
                for mv in ("public.mv_brand_monthly", "public.mv_category_monthly"):
                    cur.execute(f"REFRESH MATERIALIZED VIEW {mv}")
                    print(f"  refreshed {mv}")
    elif args.commit:
        print("\nNOTE: materialized views are now STALE. Refresh them with:")
        print("  REFRESH MATERIALIZED VIEW public.mv_brand_monthly;")
        print("  REFRESH MATERIALIZED VIEW public.mv_category_monthly;")
    return 0


if __name__ == "__main__":
    sys.exit(main())
