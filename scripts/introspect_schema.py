"""One-shot schema introspection for the BDSA Neon database.

Milestone 1. Assumes NOTHING about table or column names — everything is read
from pg_catalog. Produces a markdown report at reports/schema_report.md.

Usage:
    python scripts/introspect_schema.py [--schema public] [--out reports/schema_report.md]

Reads NEON_INTROSPECT_URL (preferred) or NEON_READONLY_URL from .env.
The session is forced read-only; this script never writes to the database.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg import sql

REPO_ROOT = Path(__file__).resolve().parents[1]

# A column is a candidate "dimension" if it is one of these types.
DIMENSION_TYPES = {"text", "character varying", "character", "boolean", "name", "uuid"}
TEMPORAL_TYPES = {"date", "timestamp without time zone", "timestamp with time zone"}
NUMERIC_TYPES = {
    "smallint", "integer", "bigint", "numeric", "real", "double precision", "money",
}
# Columns whose *name* suggests a period even if stored as text/int.
TIME_NAME_HINTS = ("period", "date", "month", "quarter", "week", "year", "load", "ts", "time")

# If a column has more than this many distinct values, we list only the top few.
DISTINCT_LIMIT = 200
# Sample of top values shown for high-cardinality dimensions.
HIGH_CARD_SAMPLE = 15


def load_dotenv(path: Path) -> None:
    """Minimal .env reader. Avoids a python-dotenv dependency for a one-shot script."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def fmt(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.4f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


class Introspector:
    def __init__(self, conn: psycopg.Connection, schema: str) -> None:
        self.conn = conn
        self.schema = schema
        self.out: list[str] = []

    def w(self, line: str = "") -> None:
        self.out.append(line)
        print(line, flush=True)

    def q(self, query: str, params: tuple = ()) -> list[tuple]:
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

    # -- discovery ----------------------------------------------------------

    def relations(self) -> list[tuple[str, str, str]]:
        """Returns (name, kind, comment) for tables/views/matviews in the schema."""
        rows = self.q(
            """
            SELECT c.relname,
                   CASE c.relkind WHEN 'r' THEN 'table'
                                  WHEN 'p' THEN 'partitioned table'
                                  WHEN 'v' THEN 'view'
                                  WHEN 'm' THEN 'materialized view'
                                  WHEN 'f' THEN 'foreign table'
                                  ELSE c.relkind::text END,
                   COALESCE(obj_description(c.oid, 'pg_class'), '')
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s
              AND c.relkind IN ('r','p','v','m','f')
              AND NOT c.relispartition
            ORDER BY c.relkind, c.relname
            """,
            (self.schema,),
        )
        return [(r[0], r[1], r[2]) for r in rows]

    def columns(self, table: str) -> list[dict]:
        rows = self.q(
            """
            SELECT a.attnum,
                   a.attname,
                   format_type(a.atttypid, a.atttypmod)          AS full_type,
                   t.typname                                     AS base_type,
                   NOT a.attnotnull                              AS nullable,
                   pg_get_expr(d.adbin, d.adrelid)               AS default_expr,
                   COALESCE(col_description(a.attrelid, a.attnum), '') AS comment
            FROM pg_attribute a
            JOIN pg_class c      ON c.oid = a.attrelid
            JOIN pg_namespace n  ON n.oid = c.relnamespace
            JOIN pg_type t       ON t.oid = a.atttypid
            LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
            WHERE n.nspname = %s AND c.relname = %s
              AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY a.attnum
            """,
            (self.schema, table),
        )
        cols = []
        for num, name, full_type, base_type, nullable, default_expr, comment in rows:
            # format_type gives e.g. "character varying(64)"; strip the modifier
            # to get a comparable canonical type name.
            canon = full_type.split("(")[0].strip().lower()
            cols.append(
                {
                    "num": num,
                    "name": name,
                    "type": full_type,
                    "canon": canon,
                    "base": base_type,
                    "nullable": nullable,
                    "default": default_expr,
                    "comment": comment,
                }
            )
        return cols

    def constraints(self, table: str) -> list[tuple[str, str]]:
        rows = self.q(
            """
            SELECT con.conname, pg_get_constraintdef(con.oid)
            FROM pg_constraint con
            JOIN pg_class c     ON c.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s
            ORDER BY con.contype, con.conname
            """,
            (self.schema, table),
        )
        return [(r[0], r[1]) for r in rows]

    def indexes(self, table: str) -> list[str]:
        rows = self.q(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = %s AND tablename = %s ORDER BY indexname",
            (self.schema, table),
        )
        return [r[0] for r in rows]

    def view_definition(self, table: str) -> str | None:
        rows = self.q(
            "SELECT pg_get_viewdef(format('%%I.%%I', %s::text, %s::text)::regclass, true)",
            (self.schema, table),
        )
        return rows[0][0] if rows else None

    # -- measurement --------------------------------------------------------

    def row_count(self, table: str) -> tuple[int | None, str]:
        """Exact count; falls back to the planner estimate if it times out."""
        stmt = sql.SQL("SELECT count(*) FROM {}.{}").format(
            sql.Identifier(self.schema), sql.Identifier(table)
        )
        try:
            with self.conn.cursor() as cur:
                cur.execute(stmt)
                return cur.fetchone()[0], "exact"
        except psycopg.errors.QueryCanceled:
            self.conn.rollback()
            rows = self.q(
                """
                SELECT c.reltuples::bigint
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s AND c.relname = %s
                """,
                (self.schema, table),
            )
            return (rows[0][0] if rows else None), "estimate (count(*) timed out)"

    def value_counts(self, table: str, column: str) -> tuple[list[tuple], bool]:
        """Top values by frequency. Returns (rows, is_complete).

        One GROUP BY pass gives both cardinality and frequencies. If we get back
        DISTINCT_LIMIT+1 rows the list is truncated, i.e. cardinality > limit.
        """
        stmt = sql.SQL(
            "SELECT {col}, count(*) AS n FROM {sch}.{tbl} GROUP BY 1 ORDER BY n DESC, 1 LIMIT {lim}"
        ).format(
            col=sql.Identifier(column),
            sch=sql.Identifier(self.schema),
            tbl=sql.Identifier(table),
            lim=sql.Literal(DISTINCT_LIMIT + 1),
        )
        try:
            with self.conn.cursor() as cur:
                cur.execute(stmt)
                rows = cur.fetchall()
        except (psycopg.errors.QueryCanceled, psycopg.errors.UndefinedFunction):
            self.conn.rollback()
            return [], False
        complete = len(rows) <= DISTINCT_LIMIT
        return rows, complete

    def min_max(self, table: str, column: str, with_sum: bool = False) -> tuple | None:
        select = [
            sql.SQL("min({c})").format(c=sql.Identifier(column)),
            sql.SQL("max({c})").format(c=sql.Identifier(column)),
            sql.SQL("count({c})").format(c=sql.Identifier(column)),
            sql.SQL("count(*) - count({c})").format(c=sql.Identifier(column)),
        ]
        if with_sum:
            select.append(sql.SQL("sum({c})").format(c=sql.Identifier(column)))
        stmt = sql.SQL("SELECT {sel} FROM {sch}.{tbl}").format(
            sel=sql.SQL(", ").join(select),
            sch=sql.Identifier(self.schema),
            tbl=sql.Identifier(table),
        )
        try:
            with self.conn.cursor() as cur:
                cur.execute(stmt)
                return cur.fetchone()
        except (psycopg.errors.QueryCanceled, psycopg.errors.UndefinedFunction, psycopg.errors.DatatypeMismatch):
            self.conn.rollback()
            return None

    # -- report -------------------------------------------------------------

    def run(self) -> str:
        server = self.q("SELECT version(), current_database(), current_user")[0]
        self.w(f"# BDSA schema introspection — schema `{self.schema}`")
        self.w()
        self.w(f"- Generated: {datetime.now().isoformat(timespec='seconds')}")
        self.w(f"- Database: `{server[1]}`  ·  connected as `{server[2]}`")
        self.w(f"- Server: `{server[0].split(',')[0]}`")
        self.w()

        rels = self.relations()
        if not rels:
            self.w(f"**No relations found in schema `{self.schema}`.**")
            other = self.q(
                """
                SELECT n.nspname, count(*)
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind IN ('r','p','v','m','f')
                  AND n.nspname NOT IN ('pg_catalog','information_schema')
                GROUP BY 1 ORDER BY 2 DESC
                """
            )
            if other:
                self.w()
                self.w("Relations do exist in these schemas — rerun with `--schema`:")
                for name, n in other:
                    self.w(f"- `{name}` ({n} relations)")
            return "\n".join(self.out)

        self.w("## Relations")
        self.w()
        self.w("| relation | kind | comment |")
        self.w("| --- | --- | --- |")
        for name, kind, comment in rels:
            self.w(f"| `{name}` | {kind} | {comment or ''} |")
        self.w()

        for name, kind, comment in rels:
            self.report_relation(name, kind, comment)

        return "\n".join(self.out)

    def report_relation(self, table: str, kind: str, comment: str) -> None:
        self.w()
        self.w("---")
        self.w()
        self.w(f"## `{self.schema}.{table}` — {kind}")
        if comment:
            self.w()
            self.w(f"> {comment}")
        self.w()

        cols = self.columns(table)

        # --- DDL ---
        self.w("### DDL")
        self.w()
        self.w("```sql")
        if kind in ("view", "materialized view"):
            defn = self.view_definition(table)
            keyword = "MATERIALIZED VIEW" if kind == "materialized view" else "VIEW"
            self.w(f"CREATE {keyword} {self.schema}.{table} AS")
            self.w(defn or "  -- definition unavailable")
        else:
            self.w(f"CREATE TABLE {self.schema}.{table} (")
            parts = []
            for c in cols:
                piece = f"    {c['name']} {c['type']}"
                if c["default"]:
                    piece += f" DEFAULT {c['default']}"
                if not c["nullable"]:
                    piece += " NOT NULL"
                parts.append(piece)
            for cname, cdef in self.constraints(table):
                parts.append(f"    CONSTRAINT {cname} {cdef}")
            self.w(",\n".join(parts))
            self.w(");")
            for idxdef in self.indexes(table):
                self.w(f"{idxdef};")
        self.w("```")
        self.w()

        # --- row count ---
        count, how = self.row_count(table)
        self.w(f"**Row count:** {fmt(count)} ({how})")
        self.w()

        # --- column inventory ---
        self.w("### Columns")
        self.w()
        self.w("| # | column | type | null | default | comment |")
        self.w("| --- | --- | --- | --- | --- | --- |")
        for c in cols:
            self.w(
                f"| {c['num']} | `{c['name']}` | {c['type']} | "
                f"{'yes' if c['nullable'] else 'NO'} | {c['default'] or ''} | {c['comment']} |"
            )
        self.w()

        if not count:
            self.w("_Relation is empty — skipping value profiling._")
            return

        # --- temporal columns ---
        temporal = [
            c for c in cols
            if c["canon"] in TEMPORAL_TYPES
            or any(h in c["name"].lower() for h in TIME_NAME_HINTS)
        ]
        if temporal:
            self.w("### Temporal / period columns — min & max")
            self.w()
            self.w("| column | type | min | max | non-null | null |")
            self.w("| --- | --- | --- | --- | --- | --- |")
            for c in temporal:
                res = self.min_max(table, c["name"])
                if res is None:
                    self.w(f"| `{c['name']}` | {c['type']} | _(query failed)_ | | | |")
                    continue
                lo, hi, nn, nulls = res[0], res[1], res[2], res[3]
                self.w(
                    f"| `{c['name']}` | {c['type']} | {fmt(lo)} | {fmt(hi)} | {fmt(nn)} | {fmt(nulls)} |"
                )
            self.w()

        # --- numeric / measure columns ---
        numeric = [c for c in cols if c["canon"] in NUMERIC_TYPES and c not in temporal]
        if numeric:
            self.w("### Numeric columns — min, max, sum")
            self.w()
            self.w("| column | type | min | max | sum | non-null | null |")
            self.w("| --- | --- | --- | --- | --- | --- | --- |")
            for c in numeric:
                res = self.min_max(table, c["name"], with_sum=True)
                if res is None:
                    self.w(f"| `{c['name']}` | {c['type']} | _(query failed)_ | | | | |")
                    continue
                lo, hi, nn, nulls, total = res
                self.w(
                    f"| `{c['name']}` | {c['type']} | {fmt(lo)} | {fmt(hi)} | {fmt(total)} "
                    f"| {fmt(nn)} | {fmt(nulls)} |"
                )
            self.w()

        # --- dimension columns ---
        dims = [
            c for c in cols
            if c["canon"] in DIMENSION_TYPES or c["base"].startswith("_")
            or self.is_enum(c)
        ]
        dims = [c for c in dims if c not in temporal]
        if not dims:
            return

        self.w(f"### Dimension columns — distinct values (full list when < {DISTINCT_LIMIT})")
        self.w()
        for c in dims:
            rows, complete = self.value_counts(table, c["name"])
            if not rows:
                self.w(f"#### `{c['name']}` — _(profiling query failed or timed out)_")
                self.w()
                continue
            if complete:
                self.w(f"#### `{c['name']}` — {len(rows)} distinct value(s), complete list")
                self.w()
                self.w("| value | rows |")
                self.w("| --- | --- |")
                for value, n in rows:
                    shown = "`NULL`" if value is None else f"`{value}`"
                    self.w(f"| {shown} | {fmt(n)} |")
            else:
                self.w(
                    f"#### `{c['name']}` — high cardinality (> {DISTINCT_LIMIT} distinct); "
                    f"top {HIGH_CARD_SAMPLE} by row count"
                )
                self.w()
                self.w("| value | rows |")
                self.w("| --- | --- |")
                for value, n in rows[:HIGH_CARD_SAMPLE]:
                    shown = "`NULL`" if value is None else f"`{value}`"
                    self.w(f"| {shown} | {fmt(n)} |")
            self.w()

    def is_enum(self, col: dict) -> bool:
        rows = self.q(
            "SELECT 1 FROM pg_type WHERE typname = %s AND typtype = 'e'", (col["base"],)
        )
        return bool(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", default="public")
    ap.add_argument("--out", default="reports/schema_report.md")
    ap.add_argument(
        "--timeout-ms",
        type=int,
        default=120_000,
        help="Statement timeout for introspection. Generous on purpose: count(*) "
             "over the full fact table is slower than any runtime query.",
    )
    args = ap.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    dsn = os.environ.get("NEON_INTROSPECT_URL") or os.environ.get("NEON_READONLY_URL")
    if not dsn:
        print(
            "ERROR: no connection string. Set NEON_INTROSPECT_URL or NEON_READONLY_URL "
            f"in {REPO_ROOT / '.env'} (see .env.example).",
            file=sys.stderr,
        )
        return 2

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SET default_transaction_read_only = on")
            cur.execute(f"SET statement_timeout = {int(args.timeout_ms)}")
        report = Introspector(conn, args.schema).run()

    out_path = REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report + "\n", encoding="utf-8")
    print(f"\n\n[written] {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
