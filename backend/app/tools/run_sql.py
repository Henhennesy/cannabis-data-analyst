"""run_sql -- the escape hatch, and the log of what the other tools do not cover.

Every invocation is appended to backend/logs/run_sql.jsonl, accepted or
rejected. That log is the point as much as the query is: a question the model
had to drop to raw SQL for is a question the parameterised tools should
probably cover, and the log is the evidence for promoting one.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from ..config import MAX_ROWS, get_settings
from ..db import run_query
from ..envelope import Coverage, ToolEnvelope
from ..sql_guard import enforce_limit, validate

log = logging.getLogger(__name__)

TOOL_NAME = "run_sql"
_log_lock = threading.Lock()

ANTHROPIC_TOOL = {
    "name": TOOL_NAME,
    "description": (
        "Escape hatch: run one read-only SELECT against the database when no other "
        "tool can answer the question. Prefer the parameterised tools whenever they "
        "fit -- they carry coverage, suppression handling and the partial-year rules "
        "for you, and this tool does not. "
        "A single SELECT or WITH only; the connection is read-only and a row limit is "
        "enforced. The fact table is public.bdsa_sales; public.mv_category_monthly and "
        "public.mv_brand_monthly are annual rollups that exclude suppressed rows. "
        "Remember the gotchas: edibles are category_l2='Edibles' under "
        "category_l1='Ingestibles', the inhalation category is spelled 'Inhaleables', "
        "fast_acting is non-null only on edibles, and dollars are total_retail_sales "
        "on the fact table but total_sales on the views."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "One SELECT statement."},
            "purpose": {
                "type": "string",
                "description": (
                    "One line on what this answers and why an existing tool could not. "
                    "Logged so uncovered questions can be promoted to real tools."
                ),
            },
        },
        "required": ["query", "purpose"],
        "additionalProperties": False,
    },
}


class RunSqlInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    purpose: str = ""


def _record(entry: dict) -> None:
    """Append one JSONL line. Never let logging break the tool."""
    try:
        path = get_settings().run_sql_log_path
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, default=str)
        with _log_lock, open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:  # noqa: BLE001
        log.exception("could not write run_sql log")


def run_sql(inp: RunSqlInput) -> ToolEnvelope:
    started = datetime.now(timezone.utc).isoformat()
    verdict = validate(inp.query)

    if not verdict.ok:
        _record({
            "at": started,
            "purpose": inp.purpose,
            "query": inp.query,
            "accepted": False,
            "reason": verdict.reason,
        })
        return ToolEnvelope.failed(verdict.reason, params={"query": inp.query})

    guarded = enforce_limit(inp.query, MAX_ROWS)
    t0 = time.perf_counter()

    try:
        result = run_query(guarded, {}, max_rows=MAX_ROWS)
    except psycopg.errors.QueryCanceled:
        _record({
            "at": started, "purpose": inp.purpose, "query": inp.query,
            "accepted": True, "failed": "timeout",
            "seconds": round(time.perf_counter() - t0, 3),
        })
        return ToolEnvelope.failed(
            "The query exceeded the statement timeout. Narrow it -- filter to a "
            "single year or state, or aggregate rather than returning detail rows.",
            sql_text=guarded,
            params={"query": inp.query},
        )
    except psycopg.Error as exc:
        message = str(exc).strip().splitlines()[0]
        _record({
            "at": started, "purpose": inp.purpose, "query": inp.query,
            "accepted": True, "failed": message,
            "seconds": round(time.perf_counter() - t0, 3),
        })
        # Hand the database's own message back: the model can usually correct a
        # typo'd column from it, and it is honest about what went wrong.
        return ToolEnvelope.failed(
            f"The database rejected the query: {message}",
            sql_text=guarded,
            params={"query": inp.query},
        )

    elapsed = round(time.perf_counter() - t0, 3)
    _record({
        "at": started, "purpose": inp.purpose, "query": inp.query,
        "accepted": True, "row_count": result.row_count,
        "truncated": result.truncated, "seconds": elapsed,
    })

    notes = [
        "BDSA is retail sell-through in covered states only. It is not total market.",
        "This is raw SQL. Coverage was NOT derived for it -- state the period and the "
        "state set from your own query, and check them against describe_coverage.",
        "Suppression was not handled for you. The fact table includes suppressed rows "
        "unless you filtered is_suppressed = false; the materialized views exclude "
        "them already.",
    ]
    if result.truncated:
        notes.append(
            f"Truncated at {MAX_ROWS} rows. Aggregate or narrow the query rather than "
            f"describing the rows you cannot see."
        )
    if result.row_count == 0:
        notes.append(
            "Zero rows. That is an empty result, not a zero market -- check the filter "
            "values before reporting anything."
        )

    return ToolEnvelope(
        rows=result.rows,
        row_count=result.row_count,
        sql=result.sql,
        params={"query": inp.query, "purpose": inp.purpose},
        # Left empty on purpose: nothing here can infer the period or state set
        # from arbitrary SQL, and guessing would be worse than saying nothing.
        coverage=Coverage(),
        truncated=result.truncated,
        relation="(raw sql)",
        notes=notes,
    )
