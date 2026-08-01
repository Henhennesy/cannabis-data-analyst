"""Validation for the `run_sql` escape hatch.

This is the one path where the model composes SQL freely, so it gets the most
scrutiny. Three independent layers, in order of how much they are trusted:

  1. The read-only Postgres role. This is the real guarantee -- `bdsa_readonly`
     holds no INSERT/UPDATE/DELETE/TRUNCATE privilege and cannot create
     anything, verified empirically by scripts/verify_readonly.py. Even a total
     failure of everything below cannot write to the database.
  2. The 8s statement timeout, which bounds a runaway query.
  3. This module, which rejects statements that are not a single read.

Layer 3 exists because a clear rejection the model can read and correct is far
more useful than a permission-denied error it cannot interpret -- and because
defence in depth means not relying on any single layer being perfect.

Keyword scanning happens on a SANITISED copy with comments and string literals
removed, so a keyword inside a string cannot trip a false positive and a
comment cannot smuggle one past.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Anything that writes, changes session state, or executes something other than
# a plain read. Matched on word boundaries against sanitised text.
FORBIDDEN = {
    # writes
    "INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE", "UPSERT",
    # DDL
    "CREATE", "ALTER", "DROP", "RENAME", "COMMENT",
    # SELECT ... INTO creates a table
    "INTO",
    # privileges
    "GRANT", "REVOKE", "REASSIGN", "SECURITY",
    # bulk / external IO
    "COPY", "IMPORT",
    # maintenance
    "VACUUM", "ANALYSE", "ANALYZE", "REINDEX", "CLUSTER", "REFRESH", "CHECKPOINT",
    # session and transaction state
    "SET", "RESET", "DISCARD", "LOCK", "BEGIN", "START", "COMMIT", "ROLLBACK",
    "SAVEPOINT", "RELEASE", "ABORT",
    # server-side execution
    "PREPARE", "EXECUTE", "DEALLOCATE", "DO", "CALL", "PERFORM",
    # cursors
    "DECLARE", "FETCH", "MOVE", "CLOSE",
    # async
    "LISTEN", "UNLISTEN", "NOTIFY",
    # EXPLAIN ANALYZE actually runs the query; rejecting EXPLAIN outright keeps
    # the surface minimal. Use psql for plans.
    "EXPLAIN",
}

# Functions that read the filesystem, reach the network, or burn the clock.
# The read-only role cannot call most of these, but defence in depth is cheap.
FORBIDDEN_FUNCTIONS = {
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "lo_import", "lo_export", "dblink", "dblink_exec",
    "pg_sleep", "pg_sleep_for", "pg_sleep_until",
    "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf",
    "pg_logical_emit_message", "query_to_xml",
}

MAX_QUERY_CHARS = 20_000


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    reason: str = ""
    sanitised: str = ""


def sanitise(query: str) -> str:
    """Return `query` with comments and literal contents blanked out.

    Not a parser -- a scanner good enough that keyword matching cannot be
    fooled by a keyword inside a string, or hidden inside a comment. Handles
    `--` line comments, `/* */` block comments (which nest in Postgres),
    single-quoted strings with `''` escapes, E'' backslash escapes, and
    dollar-quoted strings.
    """
    out: list[str] = []
    i, n = 0, len(query)
    while i < n:
        ch = query[i]

        # line comment
        if ch == "-" and i + 1 < n and query[i + 1] == "-":
            while i < n and query[i] != "\n":
                i += 1
            continue

        # block comment, nesting
        if ch == "/" and i + 1 < n and query[i + 1] == "*":
            depth, i = 1, i + 2
            while i < n and depth:
                if query.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif query.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            out.append(" ")
            continue

        # dollar-quoted string: $tag$ ... $tag$
        if ch == "$":
            m = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", query[i:])
            if m:
                tag = m.group(0)
                end = query.find(tag, i + len(tag))
                i = n if end == -1 else end + len(tag)
                out.append("''")
                continue

        # single-quoted string, including E'' backslash escapes
        if ch == "'":
            escaped = i > 0 and query[i - 1] in "eE"
            i += 1
            while i < n:
                if escaped and query[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if query[i] == "'":
                    if i + 1 < n and query[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append("''")
            continue

        # double-quoted identifier: kept, but contents cannot be keywords that
        # matter -- a column literally named "drop" is still just a column.
        if ch == '"':
            i += 1
            while i < n and query[i] != '"':
                i += 1
            i += 1
            out.append('"x"')
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def validate(query: str) -> GuardResult:
    raw = (query or "").strip()
    if not raw:
        return GuardResult(False, "Empty query.")
    if len(raw) > MAX_QUERY_CHARS:
        return GuardResult(
            False, f"Query is {len(raw)} characters; the limit is {MAX_QUERY_CHARS}."
        )

    clean = sanitise(raw).strip()

    # One statement only. A trailing semicolon is fine; anything after it is not.
    body = clean.rstrip().rstrip(";").rstrip()
    if ";" in body:
        return GuardResult(
            False,
            "Multiple statements are not allowed. Send exactly one SELECT.",
        )

    first = re.match(r"\(*\s*([A-Za-z_]+)", body)
    if not first or first.group(1).upper() not in {"SELECT", "WITH", "TABLE", "VALUES"}:
        return GuardResult(
            False,
            "Only a single read is allowed. The statement must begin with SELECT "
            "or WITH.",
        )

    upper = body.upper()
    for kw in sorted(FORBIDDEN):
        if re.search(rf"\b{kw}\b", upper):
            return GuardResult(
                False,
                f"The keyword {kw} is not allowed in run_sql. This tool is read-only; "
                f"use the parameterised tools for anything they cover.",
            )

    lowered = body.lower()
    for fn in sorted(FORBIDDEN_FUNCTIONS):
        if re.search(rf"\b{re.escape(fn)}\s*\(", lowered):
            return GuardResult(False, f"The function {fn}() is not allowed in run_sql.")

    return GuardResult(True, sanitised=clean)


def enforce_limit(query: str, max_rows: int) -> str:
    """Wrap the query so the row cap always applies.

    Wrapping rather than appending `LIMIT`: appending cannot override a larger
    limit the query already carries, and gets the placement wrong for anything
    with a UNION, ORDER BY, or trailing comment. A subquery wrapper is correct
    for every shape, including a leading CTE.
    """
    body = query.strip().rstrip(";").rstrip()
    return f"SELECT * FROM (\n{body}\n) AS _guarded LIMIT {int(max_rows)}"
