"""On-disk tool-result cache, keyed on (tool, params, dataset fingerprint).

SQLite rather than Redis: single user, single host, and a file that survives a
restart is the whole requirement. Including the dataset fingerprint in the key
means a data reload invalidates everything automatically -- no manual flush,
and no risk of serving last month's numbers after a load.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .config import get_settings

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        cache_path = get_settings().cache_db_path
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(cache_path, check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_cache (
                key         TEXT PRIMARY KEY,
                tool        TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                payload     TEXT NOT NULL,
                created_at  REAL NOT NULL
            )
            """
        )
        _conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tool_cache_fp ON tool_cache (fingerprint)"
        )
        _conn.commit()
    return _conn


def make_key(tool: str, params: dict[str, Any], fingerprint: str) -> str:
    canonical = json.dumps(params, sort_keys=True, default=str)
    return f"{tool}|{fingerprint}|{canonical}"


def get(tool: str, params: dict[str, Any], fingerprint: str) -> dict | None:
    key = make_key(tool, params, fingerprint)
    with _lock:
        cur = _connect().execute("SELECT payload FROM tool_cache WHERE key = ?", (key,))
        row = cur.fetchone()
    if row is None:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


def put(tool: str, params: dict[str, Any], fingerprint: str, payload: dict) -> None:
    key = make_key(tool, params, fingerprint)
    blob = json.dumps(payload, default=str)
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT OR REPLACE INTO tool_cache (key, tool, fingerprint, payload, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (key, tool, fingerprint, blob, time.time()),
        )
        conn.commit()


def purge_other_fingerprints(current: str) -> int:
    """Drop entries from previous data loads. Safe to call on startup."""
    with _lock:
        conn = _connect()
        cur = conn.execute("DELETE FROM tool_cache WHERE fingerprint <> ?", (current,))
        conn.commit()
        return cur.rowcount


def clear() -> None:
    with _lock:
        conn = _connect()
        conn.execute("DELETE FROM tool_cache")
        conn.commit()


def close() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
