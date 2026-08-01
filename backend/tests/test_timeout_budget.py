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
    ever needs to, that is a routing problem to fix, not a budget to raise.

    run_sql matters most here: it is the one path where the model composes SQL
    freely, so it is the one that must never be able to buy itself more time.
    """
    import importlib

    modules = [
        importlib.import_module(f"backend.app.tools.{t.name}")
        for t in registry.TOOLS
    ]
    modules.append(importlib.import_module("backend.app.dataset"))

    for module in modules:
        src = inspect.getsource(module)
        assert "timeout_ms" not in src, (
            f"{module.__name__} overrides the statement timeout; agent-reachable "
            f"code must keep the {get_settings().statement_timeout_ms}ms budget"
        )

    # Every registered tool was covered by the scan above.
    assert len(modules) == len(registry.TOOLS) + 1
