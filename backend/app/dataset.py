"""Dataset-level facts: what is loaded, and how to tell when it changes.

There is no load-timestamp column anywhere in the schema, and adding one would
mean changing the Neon schema, which is a stated non-goal. So the "version" of
the data is derived: the row count plus the set of source files. Any reload
changes at least one of them, which is exactly the invalidation signal the
cache needs.
"""

from __future__ import annotations

import hashlib
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


@dataclass
class CoverageSnapshot:
    years: list[int] = field(default_factory=list)
    states: list[str] = field(default_factory=list)
    period_start: int | None = None
    period_end: int | None = None
    partial_years: list[int] = field(default_factory=list)
    by_state_year: list[dict] = field(default_factory=list)
    version: DatasetVersion | None = None


def data_fingerprint() -> DatasetVersion:
    """Cheap, stable identifier for the current contents of the fact table."""
    res = run_query(
        f"""
        SELECT count(*) AS row_count,
               array_agg(DISTINCT source_file ORDER BY source_file) AS source_files
        FROM public.{FACT}
        """
    )
    row = res.rows[0]
    files = tuple(row["source_files"] or ())
    digest = hashlib.sha256(
        (str(row["row_count"]) + "|" + "|".join(files)).encode("utf-8")
    ).hexdigest()[:16]
    return DatasetVersion(row_count=row["row_count"], source_files=files, fingerprint=digest)


def partial_years_for(years: list[int]) -> list[int]:
    return sorted(y for y in years if y in KNOWN_PARTIAL_YEARS)


def caveats_for(years: list[int]) -> list[str]:
    return [PARTIAL_YEAR_CAVEAT.format(year=y) for y in partial_years_for(years)]
