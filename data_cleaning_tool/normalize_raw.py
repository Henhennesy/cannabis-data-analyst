#!/usr/bin/env python3
"""
normalize_raw.py
Bring inconsistent BDSA exports into the one shape clean_bdsa.py expects:
a delimited text file WITH the standard 26/27-column header row.

BDSA exports arrive in whatever format the download happened to produce --
.xlsx, headerless .csv, comma- or tab-delimited. clean_bdsa.py globs only
.csv/.tsv/.txt, assumes a header, and assumes one delimiter for every file
in the folder. A file that violates any of those is either skipped silently
or parsed into all-NULL rows. Both failure modes are invisible in row counts.

This script does no cleaning and no type conversion. It only re-frames the
container so the real transform in clean_bdsa.py runs unchanged.

Usage:
    python normalize_raw.py --input ./raw_exports --output ./raw_normalized
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path

# The canonical BDSA export header, in the order the columns appear in the
# file. Exports that omit "% THC Potency" are common; clean_bdsa.py already
# substitutes NULL for any column it cannot find, so a 26-column file is fine.
CANONICAL_HEADER = [
    "Year", "State",
    "Category Level 1", "Category Level 2", "Category Level 3",
    "Category Level 4", "Category Level 5",
    "Brand", "Product", "Pack Size", "Items Per Pack", "Total Item Weight",
    "Infusion Type", "Phenotype", "Strain", "Is Live Extract",
    "Mood Effect", "Cannabinoid Mix", "Sugar Free", "Fast Acting", "Flavor",
    "Total THC", "Total CBD",
    "Total Retail Sales", "Total Units", "Original List Price",
]


def fmt_cell(v: object) -> str:
    """Render a spreadsheet cell as the text an export would have contained."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        # Match the '1/1/2026 0:00' convention already present in the CSV
        # exports, which clean_bdsa.py parses with '%m/%d/%Y %H:%M'.
        return f"{v.month}/{v.day}/{v.year} {v.hour}:{v.minute:02d}"
    if isinstance(v, date):
        return f"{v.month}/{v.day}/{v.year} 0:00"
    if isinstance(v, float):
        # Avoid scientific notation and trailing .0 on whole numbers.
        if v.is_integer():
            return str(int(v))
        return f"{v:.10f}".rstrip("0").rstrip(".")
    return str(v)


def sniff_delimiter(path: Path) -> str:
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        first = f.readline()
    return "\t" if first.count("\t") > first.count(",") else ","


def looks_like_header(row: list[str]) -> bool:
    """True if the row is a header rather than data."""
    lowered = {c.strip().lower() for c in row}
    return "year" in lowered and "state" in lowered


def read_xlsx(path: Path) -> tuple[list[str], list[list[str]], bool]:
    try:
        import openpyxl
    except ImportError:
        print("ERROR: reading .xlsx needs openpyxl -> pip install openpyxl", file=sys.stderr)
        raise
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = ws.iter_rows(values_only=True)
    first = [fmt_cell(c) for c in next(rows)]
    had_header = looks_like_header(first)
    if had_header:
        header, body = first, []
    else:
        header, body = CANONICAL_HEADER[: len(first)], [first]
    body.extend([fmt_cell(c) for c in r] for r in rows)
    wb.close()
    return header, body, had_header


def read_text(path: Path) -> tuple[list[str], list[list[str]], bool]:
    delim = sniff_delimiter(path)
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        rows = [r for r in csv.reader(f, delimiter=delim) if r]
    if not rows:
        return CANONICAL_HEADER, [], False
    if looks_like_header(rows[0]):
        return rows[0], rows[1:], True
    # Headerless: positional mapping onto the canonical header.
    return CANONICAL_HEADER[: len(rows[0])], rows, False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--delimiter", default=",", help="Delimiter for the normalized output")
    args = ap.parse_args()

    in_dir, out_dir = Path(args.input), Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    sources = sorted(
        p for p in in_dir.iterdir()
        if p.suffix.lower() in {".xlsx", ".xlsm", ".csv", ".tsv", ".txt"}
    )
    if not sources:
        print(f"No input files in {in_dir}", file=sys.stderr)
        return 1

    problems = 0
    for src in sources:
        if src.suffix.lower() in {".xlsx", ".xlsm"}:
            header, body, had_header = read_xlsx(src)
            origin = "xlsx"
        else:
            header, body, had_header = read_text(src)
            origin = f"text/{'tab' if sniff_delimiter(src) == chr(9) else 'comma'}"

        widths = {len(r) for r in body}
        if len(widths) > 1:
            print(f"  !! {src.name}: ragged rows, column counts {sorted(widths)}", file=sys.stderr)
            problems += 1

        dest = out_dir / (src.stem + ".csv")
        with open(dest, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter=args.delimiter, quoting=csv.QUOTE_MINIMAL)
            w.writerow(header)
            w.writerows(body)

        years = sorted({r[0] for r in body if r})
        print(
            f"  {src.name}\n"
            f"      origin={origin}  header={'present' if had_header else 'SYNTHESIZED'}  "
            f"cols={len(header)}  rows={len(body):,}\n"
            f"      Year values: {years[:4]}{' ...' if len(years) > 4 else ''}\n"
            f"      -> {dest.name}"
        )

    print(f"\nNormalized {len(sources)} file(s) into {out_dir}")
    if problems:
        print(f"{problems} file(s) had ragged rows -- inspect before loading.", file=sys.stderr)
    print("Next:")
    print(f"  python clean_bdsa.py --input {out_dir.as_posix()} --output ./clean --delimiter ','")
    return 0


if __name__ == "__main__":
    sys.exit(main())
