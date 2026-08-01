"""The 8s statement timeout must stay the default for anything the agent can reach."""

from __future__ import annotations

import inspect

import pytest

from backend.app import db
from backend.app.config import get_settings
from backend.app.db import run_query
from backend.app.tools import registry

pytestmark = pytest.mark.db


def test_sessions_default_to_the_configured_timeout():
    res = run_query("SELECT current_setting('statement_timeout') AS t")
    assert res.rows[0]["t"] == f"{get_settings().statement_timeout_ms // 1000}s"


def test_an_override_is_restored_before_the_connection_is_reused():
    """A raised budget must not leak to the next borrower of a pooled connection."""
    run_query("SELECT 1", timeout_ms=45_000)
    after = run_query("SELECT current_setting('statement_timeout') AS t")
    assert after.rows[0]["t"] == f"{get_settings().statement_timeout_ms // 1000}s"


def test_no_agent_reachable_tool_raises_the_timeout():
    """Only maintenance and integrity checks may override the budget. If a tool
    ever needs to, that is a routing problem to fix, not a budget to raise."""
    import backend.app.tools.describe_coverage as m1
    import backend.app.tools.get_market_size as m2
    import backend.app.tools.get_segment_penetration as m3
    import backend.app.tools.list_dimension_values as m4
    import backend.app.dataset as m5

    for module in (m1, m2, m3, m4, m5):
        src = inspect.getsource(module)
        assert "timeout_ms" not in src, (
            f"{module.__name__} overrides the statement timeout; agent-reachable "
            f"code must keep the 8s budget"
        )
    assert len(registry.TOOLS) == 4
