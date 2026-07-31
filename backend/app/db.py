"""Connection pool and read-only query execution.

Every session is forced read-only and given a statement timeout. The pool
connects as the dedicated read-only role and nothing else -- see the README
for why a non-owner Neon role is not read-only by default.

Cold starts: Neon suspends the compute when idle, and the first statement
after a suspend pays a wake-up penalty that can exceed the 8s timeout no
matter how cheap the query is (an unqualified count(*) measured 8s+ cold and
0.62s warm). Raising the timeout would be the wrong fix -- it would make real
runaway queries hurt more while only masking the wake-up. Instead the pool
warms each new connection and retries a cancelled statement exactly once.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

import psycopg
from psycopg import ClientCursor, sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import MAX_ROWS, get_settings

log = logging.getLogger(__name__)

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _configure(conn: psycopg.Connection) -> None:
    """Applied once per physical connection, before it enters the pool."""
    s = get_settings()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SET default_transaction_read_only = on")
        cur.execute(f"SET statement_timeout = {int(s.statement_timeout_ms)}")
        # Wake the Neon compute now, on the pool's time rather than inside a
        # user query that is racing an 8s budget.
        cur.execute("SELECT 1")


def get_pool() -> ConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            s = get_settings()
            _pool = ConnectionPool(
                conninfo=s.require_db(),
                min_size=s.pool_min_size,
                max_size=s.pool_max_size,
                configure=_configure,
                # Recycle before Neon's own idle disconnect turns a pooled
                # connection into a surprise error mid-question.
                max_lifetime=600,
                timeout=30,
                open=True,
            )
        return _pool


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


def _tidy(query: str) -> str:
    """Collapse the indentation of a triple-quoted SQL literal."""
    lines = [ln.rstrip() for ln in query.strip("\n").rstrip().splitlines()]
    if not lines:
        return ""
    indents = [len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()]
    cut = min(indents) if indents else 0
    return "\n".join(ln[cut:] if len(ln) >= cut else ln for ln in lines)


class QueryResult:
    __slots__ = ("rows", "row_count", "sql", "params", "truncated")

    def __init__(self, rows: list[dict], sql_text: str, params: dict, truncated: bool):
        self.rows = rows
        self.row_count = len(rows)
        self.sql = sql_text
        self.params = params
        self.truncated = truncated


def run_query(
    query: str | sql.Composed | sql.SQL,
    params: dict[str, Any] | None = None,
    *,
    max_rows: int = MAX_ROWS,
) -> QueryResult:
    """Execute a read-only query and return rows plus the SQL for auditing.

    Fetches at most max_rows + 1 so truncation is detected without pulling the
    whole result into memory.
    """
    params = params or {}
    pool = get_pool()

    for attempt in (1, 2):
        try:
            with pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, params)
                    fetched = cur.fetchmany(max_rows + 1)
                # Render for display with a client-side cursor on the same
                # connection, so types are quoted exactly as the server saw them.
                with ClientCursor(conn) as ccur:
                    q = query.as_string(conn) if not isinstance(query, str) else query
                    try:
                        rendered = ccur.mogrify(q, params)
                    except Exception:
                        rendered = q
            truncated = len(fetched) > max_rows
            rows = [dict(r) for r in fetched[:max_rows]]
            return QueryResult(rows, _tidy(rendered), params, truncated)

        except psycopg.errors.QueryCanceled:
            if attempt == 1:
                # Almost always a Neon cold start: the wake-up consumed the
                # budget. The compute is awake now, so one retry is decisive.
                log.warning("statement cancelled; retrying once (likely Neon cold start)")
                continue
            raise
        except psycopg.OperationalError:
            if attempt == 1:
                log.warning("connection error; retrying once")
                continue
            raise

    raise RuntimeError("unreachable")


# --------------------------------------------------------------------------
# Identifier safety
# --------------------------------------------------------------------------

_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def safe_identifier(name: str) -> str:
    """Reject anything that is not a plain lowercase identifier.

    Column and relation names reach the SQL builders from model-supplied tool
    arguments. They are additionally checked against the schema registry, but
    this is the syntactic backstop.
    """
    if not isinstance(name, str) or not _IDENT_RE.match(name):
        raise ValueError(f"unsafe identifier: {name!r}")
    return name
