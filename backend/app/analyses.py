"""Saved analyses: persist a question and its tool calls, re-run them later.

The point is the delta. A saved analysis is not a bookmark -- it is a
re-runnable measurement. Next month's load lands, you re-run, and you see what
moved and by how much, computed by comparing tool results rather than by asking
the model to remember what it said last time.

Re-running replays the ORIGINAL tool inputs, not the original question. The
model is not consulted, so the comparison cannot drift because it happened to
phrase a query differently the second time. Same parameters, same SQL, new data.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import get_settings
from .dataset import data_fingerprint
from .envelope import ToolEnvelope
from .tools import registry

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

# Tools whose results are worth diffing. render_chart returns a spec, not data.
_DIFFABLE = lambda name: name != "render_chart"  # noqa: E731


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        db_path = get_settings().analyses_db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(db_path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analyses (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                question    TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                calls       TEXT NOT NULL
            )
            """
        )
        _conn.commit()
    return _conn


@dataclass
class SavedCall:
    tool_use_id: str
    tool_name: str
    tool_input: dict[str, Any]
    envelope: dict[str, Any]


@dataclass
class SavedAnalysis:
    id: str
    name: str
    question: str
    created_at: str
    fingerprint: str
    calls: list[SavedCall] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "question": self.question,
            "created_at": self.created_at,
            "fingerprint": self.fingerprint,
            "calls": [
                {
                    "tool_use_id": c.tool_use_id,
                    "tool_name": c.tool_name,
                    "tool_input": c.tool_input,
                    "envelope": c.envelope,
                }
                for c in self.calls
            ],
        }


def save(name: str, question: str, calls: list[dict[str, Any]]) -> SavedAnalysis:
    """Persist a question plus the tool calls that answered it."""
    analysis = SavedAnalysis(
        id=uuid.uuid4().hex[:12],
        name=name.strip() or question.strip()[:60],
        question=question,
        # Microsecond precision, not seconds: two analyses saved in the same
        # second would otherwise sort arbitrarily. The UI truncates for display.
        created_at=datetime.now(timezone.utc).isoformat(),
        fingerprint=data_fingerprint().fingerprint,
        calls=[
            SavedCall(
                tool_use_id=c["tool_use_id"],
                tool_name=c["tool_name"],
                tool_input=c.get("tool_input") or {},
                envelope=c.get("envelope") or {},
            )
            for c in calls
        ],
    )
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO analyses (id, name, question, created_at, fingerprint, calls) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                analysis.id, analysis.name, analysis.question, analysis.created_at,
                analysis.fingerprint,
                json.dumps([
                    {
                        "tool_use_id": c.tool_use_id,
                        "tool_name": c.tool_name,
                        "tool_input": c.tool_input,
                        "envelope": c.envelope,
                    }
                    for c in analysis.calls
                ], default=str),
            ),
        )
        conn.commit()
    return analysis


def _row_to_analysis(row: sqlite3.Row) -> SavedAnalysis:
    return SavedAnalysis(
        id=row["id"], name=row["name"], question=row["question"],
        created_at=row["created_at"], fingerprint=row["fingerprint"],
        calls=[
            SavedCall(
                tool_use_id=c["tool_use_id"], tool_name=c["tool_name"],
                tool_input=c["tool_input"], envelope=c["envelope"],
            )
            for c in json.loads(row["calls"])
        ],
    )


def list_all() -> list[dict[str, Any]]:
    """Summaries only -- the envelopes are large and the list does not need them."""
    with _lock:
        rows = _connect().execute(
            "SELECT id, name, question, created_at, fingerprint, calls "
            # rowid breaks ties deterministically if two timestamps still match.
            "FROM analyses ORDER BY created_at DESC, rowid DESC"
        ).fetchall()
    out = []
    for row in rows:
        calls = json.loads(row["calls"])
        out.append({
            "id": row["id"], "name": row["name"], "question": row["question"],
            "created_at": row["created_at"], "fingerprint": row["fingerprint"],
            "call_count": len(calls),
            "tools": [c["tool_name"] for c in calls],
        })
    return out


def get(analysis_id: str) -> SavedAnalysis | None:
    with _lock:
        row = _connect().execute(
            "SELECT * FROM analyses WHERE id = ?", (analysis_id,)
        ).fetchone()
    return _row_to_analysis(row) if row else None


def delete(analysis_id: str) -> bool:
    with _lock:
        conn = _connect()
        cur = conn.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
        conn.commit()
        return cur.rowcount > 0


def close() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


# ---------------------------------------------------------------------------
# Re-running and diffing
# ---------------------------------------------------------------------------

def _key_of(row: dict[str, Any]) -> str:
    """Identify a row by its non-numeric fields.

    A market-size result grouped by state is keyed by the state; the numbers are
    what changed. Sorting keeps the key stable across column reordering.
    """
    parts = [
        f"{k}={row[k]}" for k in sorted(row)
        if not isinstance(row[k], (int, float)) or isinstance(row[k], bool)
    ]
    return "|".join(parts) if parts else "(single row)"


def diff_rows(old: list[dict], new: list[dict]) -> dict[str, Any]:
    """Compare two result sets, keyed on their non-numeric columns."""
    old_by_key = {_key_of(r): r for r in old}
    new_by_key = {_key_of(r): r for r in new}

    changed: list[dict[str, Any]] = []
    for key in sorted(set(old_by_key) & set(new_by_key)):
        o, n = old_by_key[key], new_by_key[key]
        fields = []
        for col in sorted(set(o) | set(n)):
            ov, nv = o.get(col), n.get(col)
            if isinstance(ov, bool) or isinstance(nv, bool):
                continue
            if isinstance(ov, (int, float)) and isinstance(nv, (int, float)):
                if ov != nv:
                    fields.append({
                        "column": col, "before": ov, "after": nv,
                        "delta": nv - ov,
                        "pct_change": ((nv - ov) / ov * 100) if ov else None,
                    })
        if fields:
            changed.append({"key": key, "fields": fields})

    return {
        "added": [{"key": k, "row": new_by_key[k]} for k in sorted(set(new_by_key) - set(old_by_key))],
        "removed": [{"key": k, "row": old_by_key[k]} for k in sorted(set(old_by_key) - set(new_by_key))],
        "changed": changed,
        "unchanged_count": len(set(old_by_key) & set(new_by_key)) - len(changed),
    }


def rerun(analysis_id: str) -> dict[str, Any] | None:
    """Replay the saved tool calls against current data and diff the results."""
    analysis = get(analysis_id)
    if analysis is None:
        return None

    current = data_fingerprint().fingerprint
    turn_results: dict[str, ToolEnvelope] = {}
    results = []

    for call in analysis.calls:
        envelope = registry.dispatch(call.tool_name, call.tool_input, turn_results)
        # Key by the ORIGINAL id so a saved render_chart still resolves.
        turn_results[call.tool_use_id] = envelope

        entry: dict[str, Any] = {
            "tool_use_id": call.tool_use_id,
            "tool_name": call.tool_name,
            "tool_input": call.tool_input,
            "before": call.envelope,
            "after": envelope.model_dump(),
            "diff": None,
        }
        if _DIFFABLE(call.tool_name) and not envelope.error and not call.envelope.get("error"):
            entry["diff"] = diff_rows(call.envelope.get("rows") or [], envelope.rows)
        results.append(entry)

    return {
        "analysis": analysis.to_json(),
        "saved_fingerprint": analysis.fingerprint,
        "current_fingerprint": current,
        "data_changed": current != analysis.fingerprint,
        "results": results,
    }
