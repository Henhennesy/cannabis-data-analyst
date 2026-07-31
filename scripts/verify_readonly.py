#!/usr/bin/env python3
"""
verify_readonly.py
Prove that NEON_READONLY_URL cannot write.

A role that is *believed* to be read-only is worth nothing. Neon's console
grants new roles membership in neon_superuser, which inherits
pg_write_all_data, so a role named "Read Only" can happily TRUNCATE your fact
table. This script establishes the guarantee empirically.

It tests TWO independent layers, because they fail differently:

  1. With the role's default session settings, where
     default_transaction_read_only = on should reject writes.
  2. With that setting explicitly turned OFF, which is the real test. If
     writes are blocked only by the session default, anyone who runs
     SET default_transaction_read_only = off can write. Only a privilege
     failure here means the role is genuinely incapable of writing.

Every write probe uses WHERE false / SELECT ... WHERE false, so it affects
zero rows even in the failure case where the privilege check passes. Each runs
in its own transaction and is always rolled back.

Usage:
    python scripts/verify_readonly.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from introspect_schema import load_dotenv  # noqa: E402

# Zero-row by construction: the privilege check still runs, but nothing can
# be written even if the check unexpectedly passes.
WRITE_PROBES = [
    ("INSERT", "INSERT INTO public.bdsa_sales (state) SELECT 'probe' WHERE false"),
    ("UPDATE", "UPDATE public.bdsa_sales SET state = state WHERE false"),
    ("DELETE", "DELETE FROM public.bdsa_sales WHERE false"),
    ("TRUNCATE-priv", "SELECT has_table_privilege('public.bdsa_sales', 'TRUNCATE')"),
    ("CREATE TABLE", "CREATE TABLE public._readonly_probe (i int)"),
]

# Deliberately cheap: these test SELECT *privilege*, not query performance.
# count(*) over the 7.4M-row fact table exceeds the role's 8s statement
# timeout, which is a real constraint on tool design but not a permission
# problem, and conflating the two makes this check useless.
READ_PROBES = [
    ("SELECT fact table", "SELECT state FROM public.bdsa_sales LIMIT 1"),
    ("SELECT mv_brand_monthly", "SELECT count(*) FROM public.mv_brand_monthly"),
    ("SELECT mv_category_monthly", "SELECT count(*) FROM public.mv_category_monthly"),
]


def probe(conn: psycopg.Connection, sql: str) -> tuple[bool, str]:
    """Run sql in its own transaction and always roll back."""
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            try:
                out = cur.fetchone()
            except psycopg.ProgrammingError:
                out = None
        conn.rollback()
        return True, ("" if out is None else str(out[0]))
    except psycopg.Error as e:
        conn.rollback()
        return False, str(e).strip().splitlines()[0]


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    dsn = os.environ.get("NEON_READONLY_URL")
    if not dsn:
        print("ERROR: NEON_READONLY_URL is not set in .env", file=sys.stderr)
        return 2

    failures: list[str] = []

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_user, current_database(), "
                        "current_setting('default_transaction_read_only'), "
                        "current_setting('statement_timeout')")
            user, db, ro, timeout = cur.fetchone()
        conn.rollback()

        print("=" * 78)
        print("IDENTITY AND SESSION DEFAULTS")
        print("=" * 78)
        print(f"  connected as        : {user}")
        print(f"  database            : {db}")
        print(f"  read-only session   : {ro}")
        print(f"  statement_timeout   : {timeout}")
        if ro != "on":
            failures.append("default_transaction_read_only is not 'on' for this role")
        if timeout in ("0", ""):
            failures.append("statement_timeout is not set for this role")

        with conn.cursor() as cur:
            cur.execute("""
                SELECT ARRAY(SELECT b.rolname FROM pg_auth_members m
                             JOIN pg_roles b ON b.oid = m.roleid
                             WHERE m.member = r.oid ORDER BY 1),
                       r.rolsuper, r.rolcreatedb, r.rolcreaterole, r.rolbypassrls
                FROM pg_roles r WHERE r.rolname = current_user
            """)
            memberof, sup, cdb, crole, rls = cur.fetchone()
        conn.rollback()
        print(f"  member of           : {memberof}")
        print(f"  superuser={sup}  createdb={cdb}  createrole={crole}  bypassrls={rls}")
        if "neon_superuser" in (memberof or []):
            failures.append("role inherits neon_superuser -> it can write via pg_write_all_data")
        for flag, name in ((sup, "SUPERUSER"), (cdb, "CREATEDB"), (crole, "CREATEROLE"),
                           (rls, "BYPASSRLS")):
            if flag:
                failures.append(f"role has {name}")

        print()
        print("=" * 78)
        print("READS -- must all SUCCEED")
        print("=" * 78)
        for label, sql in READ_PROBES:
            ok, msg = probe(conn, sql)
            print(f"  {label:<28} {'OK' if ok else 'FAILED'}  {msg[:60]}")
            if not ok:
                failures.append(f"read failed: {label} -- {msg}")

        print()
        print("=" * 78)
        print("WRITES, layer 1 -- role's own session defaults")
        print("=" * 78)
        for label, sql in WRITE_PROBES:
            ok, msg = probe(conn, sql)
            if label == "TRUNCATE-priv":
                bad = (msg.lower() == "true")
                print(f"  {label:<28} has_privilege={msg}  {'<-- CAN TRUNCATE' if bad else 'denied'}")
                if bad:
                    failures.append("role holds TRUNCATE privilege on bdsa_sales")
                continue
            print(f"  {label:<28} {'SUCCEEDED <-- BAD' if ok else 'blocked'}  {msg[:70]}")
            if ok:
                failures.append(f"write allowed under default session: {label}")

    print()
    print("=" * 78)
    print("WRITES, layer 2 -- read-only session default DISABLED")
    print("=" * 78)
    print("  (if writes are blocked only by the session flag, anyone can turn it off)")

    # A fresh AUTOCOMMIT connection is required. default_transaction_read_only
    # sets the default for *future* transactions -- issuing it inside an open
    # transaction leaves that transaction read-only, so the probes would just
    # re-test layer 1 and report a false pass.
    with psycopg.connect(dsn, autocommit=True) as conn2:
        with conn2.cursor() as cur:
            cur.execute("SET default_transaction_read_only = off")
            cur.execute("SET statement_timeout = 30000")
            cur.execute("SELECT current_setting('default_transaction_read_only'), "
                        "current_setting('transaction_read_only')")
            sess, txn = cur.fetchone()
        print(f"  session default now: {sess}   current transaction read_only: {txn}")
        if sess != "off":
            failures.append("could not disable the session read-only flag -- layer 2 untested")

        for label, sql in WRITE_PROBES:
            if label == "TRUNCATE-priv":
                continue
            try:
                with conn2.cursor() as cur:
                    cur.execute(sql)
                ok, msg = True, ""
            except psycopg.Error as e:
                ok, msg = False, str(e).strip().splitlines()[0]
            if ok and label == "CREATE TABLE":
                with conn2.cursor() as cur:
                    cur.execute("DROP TABLE IF EXISTS public._readonly_probe")
            reason = "PRIVILEGE" if "permission denied" in msg.lower() else "read-only txn"
            print(f"  {label:<28} {'SUCCEEDED <-- BAD' if ok else f'blocked ({reason})'}  {msg[:56]}")
            if ok:
                failures.append(f"PRIVILEGE HOLE: {label} allowed once session flag is off")
            elif reason != "PRIVILEGE":
                failures.append(
                    f"{label} blocked only by the read-only transaction flag, not by privilege")

    print()
    print("=" * 78)
    if failures:
        print(f"RESULT: NOT SAFE -- {len(failures)} problem(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: role is genuinely read-only. Reads work; writes are")
    print("        blocked by privilege, not merely by a session setting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
