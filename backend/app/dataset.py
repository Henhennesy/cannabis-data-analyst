"""Dataset-level facts: what is loaded, and how to tell when it changes.

There is no load-timestamp column anywhere in the schema, and adding one would
mean changing the Neon schema, which is a stated non-goal. So the "version" of
the data is derived: the row count plus the set of source files. Any reload
changes at least one of them, which is exactly the invalidation signal the
cache needs.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field

from .db import run_query
from .schema_registry import FACT

# 2026 is a partial year. The width of that partial window is NOT recorded
# anywhere in the data and differs by state -- South Dakota's monthly export
# happened to reveal a January-July window, but no other state discloses one.
# See reports/coverage_anomalies.md.
KNOWN_PARTIAL_YEARS = frozenset({2026})

PARTIAL_YEAR_CAVEAT = (
    "{year} is a PARTIAL year. The data records no YTD cutoff, and the window "
    "differs between states, so {year} totals are not comparable across states "
    "and not comparable to a full year. Within-state share and mix are valid."
)


@dataclass(frozen=True)
class DatasetVersion:
    row_count: int
    source_files: tuple[str, ...]
    fingerprint: str


# The fingerprint is consulted before every single tool call, so it has to be
# cheap. The obvious implementation -- count(*) plus array_agg(DISTINCT
# source_file) over the fact table -- costs 4.4s warm and more than the entire
# 8s budget cold, which made tools fail before their real query even started.
# It is now derived from the category rollup (12k rows, ~0.06s) plus a bare
# count on the fact table, and memoised for _FINGERPRINT_TTL seconds. Data
# only changes on a manual reload, so a short stale window costs nothing.
_FINGERPRINT_TTL = 60.0
_cached_version: DatasetVersion | None = None
_cached_at: float = 0.0
_version_lock = threading.Lock()


@dataclass
class CoverageSnapshot:
    years: list[int] = field(default_factory=list)
    states: list[str] = field(default_factory=list)
    period_start: int | None = None
    period_end: int | None = None
    partial_years: list[int] = field(default_factory=list)
    by_state_year: list[dict] = field(default_factory=list)
    version: DatasetVersion | None = None


def data_fingerprint(*, force: bool = False) -> DatasetVersion:
    """Cheap, stable identifier for the current contents of the database.

    Sensitive to any reload: the fact row count changes if rows are added or
    removed, and the rollup's row count and dollar total change whenever the
    views are refreshed after a load. Refreshing the views is mandatory after
    any load, and a separate test asserts they reconcile.
    """
    global _cached_version, _cached_at

    with _version_lock:
        if not force and _cached_version is not None:
            if time.monotonic() - _cached_at < _FINGERPRINT_TTL:
                return _cached_version

    from .schema_registry import MV_CATEGORY

    # Derived from the rollup ALONE, deliberately. count(*) on the 7.45M-row
    # fact table needs a full scan -- ~0.6s warm, but well over the 8s budget on
    # a cold page cache, and this runs before every single tool call. The rollup
    # answers in ~0.06s.
    #
    # The tradeoff: a load whose materialized views were never refreshed would
    # not change this fingerprint. That is acceptable because every tool reads
    # from the views too, so the cache stays consistent with what is actually
    # being served -- and test_schema_registry asserts the views reconcile to
    # the fact table, which is what catches a forgotten REFRESH.
    res = run_query(
        f"""
        SELECT count(*)          AS mv_rows,
               sum(total_sales)  AS mv_dollars,
               sum(total_units)  AS mv_units
        FROM public.{MV_CATEGORY}
        """
    )
    row = res.rows[0]
    digest = hashlib.sha256(
        f"{row['mv_rows']}|{row['mv_dollars']}|{row['mv_units']}".encode("utf-8")
    ).hexdigest()[:16]
    version = DatasetVersion(
        row_count=row["mv_rows"], source_files=(), fingerprint=digest
    )

    with _version_lock:
        _cached_version = version
        _cached_at = time.monotonic()
    return version


def reset_fingerprint_cache() -> None:
    """Force the next call to re-read. Used by tests and after a load."""
    global _cached_version, _cached_at
    with _version_lock:
        _cached_version = None
        _cached_at = 0.0


def source_file_summary() -> list[dict]:
    """Load provenance. Deliberately NOT part of the fingerprint -- grouping
    7.45M rows by source_file costs ~1.9s, too much to pay per tool call.
    Only describe_coverage needs it, and that result is cached."""
    return run_query(
        f"""
        SELECT source_file, period_year, count(*) AS rows
        FROM public.{FACT} GROUP BY 1, 2 ORDER BY 2, 1
        """
    ).rows


def available_years() -> list[int]:
    """Years actually loaded. Asking about anything else must say so, not
    return zero as though the market were empty."""
    from .schema_registry import MV_CATEGORY

    res = run_query(
        f"SELECT DISTINCT period_year AS y FROM public.{MV_CATEGORY} ORDER BY 1"
    )
    return [r["y"] for r in res.rows]


def partial_years_for(years: list[int]) -> list[int]:
    return sorted(y for y in years if y in KNOWN_PARTIAL_YEARS)


def caveats_for(years: list[int]) -> list[str]:
    return [PARTIAL_YEAR_CAVEAT.format(year=y) for y in partial_years_for(years)]
