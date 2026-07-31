"""Test configuration.

Every test runs against the REAL Neon database. No fixtures, no fabricated
rows, no mocks of the data layer -- a mock cannot tell you that
`category_l1 = 'Edibles'` returns nothing, which is the entire class of bug
these tests exist to catch.

Tests are read-only by construction: the pool connects as bdsa_readonly, which
has no write privilege at all (see scripts/verify_readonly.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend.app import cache  # noqa: E402
from backend.app.config import get_settings  # noqa: E402
from backend.app.dataset import reset_fingerprint_cache  # noqa: E402
from backend.app.db import close_pool  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "db: touches the live Neon database")


@pytest.fixture(scope="session", autouse=True)
def require_database():
    s = get_settings()
    if not s.readonly_url:
        pytest.skip("NEON_READONLY_URL not configured", allow_module_level=True)
    yield
    close_pool()


@pytest.fixture(autouse=True)
def clean_cache():
    """Tests must exercise real queries, not each other's cached results.

    The fingerprint memo is left intact on purpose: it is a per-process
    optimisation, not test state, and clearing it would add a redundant
    round-trip to every single test.
    """
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def fresh_fingerprint():
    """For tests that need the fingerprint recomputed from the database."""
    reset_fingerprint_cache()
    yield
    reset_fingerprint_cache()
