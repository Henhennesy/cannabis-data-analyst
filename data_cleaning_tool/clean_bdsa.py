#!/usr/bin/env python3
"""
clean_bdsa.py
Clean and merge BDSA retail export files (tab-delimited) into a single
load-ready dataset for Postgres/Neon.

Usage:
    pip install duckdb
    python clean_bdsa.py --input ./raw_exports --output ./clean

Drop every BDSA export (.csv / .tsv / .txt, tab-delimited) into the input
folder. Re-run any time you add new states or years. The script:

  1. Reads all files (streaming, low memory) and unions them by column name
  2. Normalizes headers to snake_case
  3. Parses the monthly period into a proper DATE
  4. Trims whitespace and collapses internal double-spaces in text fields
  5. Converts empty strings to NULL
  6. Casts metrics to numeric types
  7. Flags suppressed/masked rows (e.g. $0.01-per-unit placeholders)
  8. Removes exact duplicate rows (e.g. from overlapping exports)
  9. Writes:  bdsa_clean.parquet   (archival / fast re-processing)
              bdsa_clean.csv      (for psql \\copy into Neon)
              qa_report.txt       (row counts, flags, brand variants)
"""

import argparse
import sys
from pathlib import Path

import duckdb

RAW_COLUMNS = {
    "Year": "period_raw",
    "State": "state",
    "Category Level 1": "category_l1",
    "Category Level 2": "category_l2",
    "Category Level 3": "category_l3",
    "Category Level 4": "category_l4",
    "Category Level 5": "category_l5",
    "Brand": "brand",
    "Product": "product",
    "Pack Size": "pack_size",
    "Items Per Pack": "items_per_pack",
    "Total Item Weight": "total_item_weight",
    "Infusion Type": "infusion_type",
    "Phenotype": "phenotype",
    "% THC Potency": "pct_thc_potency",
    "Strain": "strain",
    "Is Live Extract": "is_live_extract",
    "Mood Effect": "mood_effect",
    "Cannabinoid Mix": "cannabinoid_mix",
    "Sugar Free": "sugar_free",
    "Fast Acting": "fast_acting",
    "Flavor": "flavor",
    "Total THC": "total_thc_mg",
    "Total CBD": "total_cbd_mg",
    "Total Retail Sales": "total_retail_sales",
    "Total Units": "total_units",
    "Original List Price": "original_list_price",
}

TEXT_COLS = [
    "state", "category_l1", "category_l2", "category_l3", "category_l4",
    "category_l5", "brand", "product", "pack_size", "infusion_type",
    "phenotype", "strain", "is_live_extract", "mood_effect",
    "cannabinoid_mix", "sugar_free", "fast_acting", "flavor",
    "total_item_weight",
]

NUMERIC_COLS = [
    "items_per_pack", "pct_thc_potency", "total_thc_mg", "total_cbd_mg",
    "total_retail_sales", "total_units", "original_list_price",
]

# Rows where revenue-per-unit is below this are treated as BDSA
# suppression/masking placeholders ($0.01 x N units patterns).
SUPPRESSION_PRICE_THRESHOLD = 0.25


def clean_expr(col: str) -> str:
    """Trim, collapse whitespace, NULL out empties."""
    return (
        f"NULLIF(TRIM(REGEXP_REPLACE(\"{col}\", '\\s+', ' ', 'g')), '') "
        f"AS {col}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Folder of raw BDSA exports")
    ap.add_argument("--output", required=True, help="Folder for cleaned output")
    ap.add_argument(
        "--delimiter", default="\t",
        help="Field delimiter in the raw files (default: tab)",
    )
    args = ap.parse_args()

    in_dir = Path(args.input)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(
        p for p in in_dir.iterdir()
        if p.suffix.lower() in {".csv", ".tsv", ".txt"}
    )
    if not files:
        print(f"No .csv/.tsv/.txt files found in {in_dir}", file=sys.stderr)
        return 1

    print(f"Found {len(files)} file(s):")
    for p in files:
        print(f"  {p.name}  ({p.stat().st_size / 1e6:.1f} MB)")

    con = duckdb.connect()
    con.execute("PRAGMA threads=4;")

    file_list = "[" + ", ".join(f"'{p.as_posix()}'" for p in files) + "]"

    # 1. Raw union of all files, everything as VARCHAR, keep filename
    con.execute(f"""
        CREATE OR REPLACE VIEW raw AS
        SELECT * FROM read_csv(
            {file_list},
            delim='{args.delimiter}',
            header=true,
            all_varchar=true,
            union_by_name=true,
            filename=true,
            quote='"',
            sample_size=-1
        );
    """)

    raw_cols = [r[0] for r in con.execute("DESCRIBE raw").fetchall()]
    missing = [c for c in RAW_COLUMNS if c not in raw_cols]
    if missing:
        print(
            "WARNING: expected columns missing from the exports "
            f"(they will be NULL): {missing}",
            file=sys.stderr,
        )

    select_renames = ", ".join(
        f'"{raw}" AS {new}' if raw in raw_cols else f"NULL AS {new}"
        for raw, new in RAW_COLUMNS.items()
    )

    con.execute(f"""
        CREATE OR REPLACE VIEW renamed AS
        SELECT {select_renames}, filename AS source_file
        FROM raw;
    """)

    # 2. Clean text, cast numerics, parse the period date
    text_exprs = ",\n            ".join(clean_expr(c) for c in TEXT_COLS)
    num_exprs = ",\n            ".join(
        f"TRY_CAST(NULLIF(TRIM({c}), '') AS DOUBLE) AS {c}"
        for c in NUMERIC_COLS
    )

    con.execute(f"""
        CREATE OR REPLACE VIEW cleaned AS
        SELECT
            COALESCE(
                TRY_CAST(TRY_STRPTIME(TRIM(period_raw), '%m/%d/%Y %H:%M') AS DATE),
                TRY_CAST(TRY_STRPTIME(TRIM(period_raw), '%m/%d/%Y') AS DATE),
                TRY_CAST(TRIM(period_raw) AS DATE)
            ) AS period_month,
            {text_exprs},
            {num_exprs},
            source_file
        FROM renamed;
    """)

    # 3. Dedupe exact duplicates (ignoring source file), add flags
    con.execute(f"""
        CREATE OR REPLACE TABLE final AS
        SELECT
            * EXCLUDE (source_file),
            ANY_VALUE(source_file) AS source_file,
            EXTRACT(year FROM period_month)::INT AS period_year,
            CASE
                WHEN total_retail_sales IS NULL OR total_units IS NULL
                     OR total_units = 0 THEN FALSE
                WHEN total_retail_sales / total_units
                     < {SUPPRESSION_PRICE_THRESHOLD} THEN TRUE
                ELSE FALSE
            END AS is_suppressed
        FROM cleaned
        GROUP BY ALL;
    """)

    # 4. QA report
    total = con.execute("SELECT COUNT(*) FROM final").fetchone()[0]
    raw_total = con.execute("SELECT COUNT(*) FROM cleaned").fetchone()[0]
    suppressed = con.execute(
        "SELECT COUNT(*) FROM final WHERE is_suppressed"
    ).fetchone()[0]
    bad_dates = con.execute(
        "SELECT COUNT(*) FROM final WHERE period_month IS NULL"
    ).fetchone()[0]

    per_file = con.execute("""
        SELECT source_file, COUNT(*) AS rows,
               MIN(period_month) AS min_month, MAX(period_month) AS max_month,
               COUNT(DISTINCT state) AS states
        FROM final GROUP BY 1 ORDER BY 1
    """).fetchall()

    brand_variants = con.execute("""
        WITH norm AS (
            SELECT DISTINCT brand, LOWER(brand) AS brand_key
            FROM final WHERE brand IS NOT NULL
        )
        SELECT brand_key, LIST(brand ORDER BY brand) AS variants
        FROM norm
        GROUP BY brand_key
        HAVING COUNT(*) > 1
        ORDER BY brand_key
    """).fetchall()

    report_path = out_dir / "qa_report.txt"
    with open(report_path, "w") as f:
        f.write("BDSA CLEANING QA REPORT\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Files processed:        {len(files)}\n")
        f.write(f"Rows read:              {raw_total:,}\n")
        f.write(f"Rows after dedupe:      {total:,}\n")
        f.write(f"Exact dupes removed:    {raw_total - total:,}\n")
        f.write(f"Suppressed-row flags:   {suppressed:,}"
                f"  ({100 * suppressed / max(total, 1):.2f}%)\n")
        f.write(f"Unparseable dates:      {bad_dates:,}\n\n")
        f.write("Per-file summary:\n")
        for row in per_file:
            f.write(f"  {Path(row[0]).name}: {row[1]:,} rows, "
                    f"{row[2]} to {row[3]}, {row[4]} state(s)\n")
        f.write("\nBrand casing variants (same name, different "
                "capitalization), review before merging:\n")
        if not brand_variants:
            f.write("  none found\n")
        for key, variants in brand_variants:
            f.write(f"  {variants}\n")

    # 5. Outputs
    parquet_path = out_dir / "bdsa_clean.parquet"
    csv_path = out_dir / "bdsa_clean.csv"
    con.execute(f"COPY final TO '{parquet_path.as_posix()}' (FORMAT PARQUET);")
    con.execute(
        f"COPY final TO '{csv_path.as_posix()}' "
        f"(FORMAT CSV, HEADER, DELIMITER ',');"
    )

    print(f"\nDone. {total:,} rows written.")
    print(f"  {parquet_path}")
    print(f"  {csv_path}")
    print(f"  {report_path}")
    print("\nNext: create the schema in Neon (schema.sql), then load with:")
    print("  psql \"$NEON_CONNECTION_STRING\" -c "
          "\"\\copy bdsa_sales FROM 'clean/bdsa_clean.csv' CSV HEADER\"")
    print("  psql \"$NEON_CONNECTION_STRING\" -c "
          "\"REFRESH MATERIALIZED VIEW mv_brand_monthly; "
          "REFRESH MATERIALIZED VIEW mv_category_monthly;\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
