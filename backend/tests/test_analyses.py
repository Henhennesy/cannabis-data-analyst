"""Saved analyses and the delta.

A saved analysis is a re-runnable measurement, not a bookmark. Re-running
replays the ORIGINAL tool inputs -- the model is never consulted -- so a
month-over-month comparison cannot drift because the model phrased its query
differently the second time.
"""

from __future__ import annotations

import importlib

import pytest

from backend.app import analyses
from backend.app.tools import GetMarketSizeInput, get_market_size

pytestmark = pytest.mark.db

EDIBLES = {"category_l1": "Ingestibles", "category_l2": "Edibles"}


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Never touch the real analyses database from a test."""
    analyses.close()
    monkeypatch.setattr(analyses, "DB_PATH", tmp_path / "analyses.sqlite")
    yield
    analyses.close()


def a_real_turn():
    """One genuine tool call, in the shape the API receives it."""
    env = get_market_size(GetMarketSizeInput(
        metric="dollar_sales", filters=EDIBLES,
        start_period=2025, end_period=2025, group_by=["state"],
    ))
    return [{
        "tool_use_id": "toolu_1",
        "tool_name": "get_market_size",
        "tool_input": {
            "metric": "dollar_sales", "filters": EDIBLES,
            "start_period": 2025, "end_period": 2025, "group_by": ["state"],
        },
        "envelope": env.model_dump(),
    }]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_saving_records_the_question_the_calls_and_the_data_version():
    saved = analyses.save("Edibles by state", "Which states lead edibles?", a_real_turn())
    assert saved.id
    assert saved.name == "Edibles by state"
    assert saved.fingerprint          # what the data looked like when saved
    assert len(saved.calls) == 1
    assert saved.calls[0].tool_name == "get_market_size"


def test_an_unnamed_analysis_falls_back_to_the_question():
    saved = analyses.save("", "Which states lead edibles in 2025?", a_real_turn())
    assert saved.name.startswith("Which states lead")


def test_listing_omits_the_envelopes_but_keeps_the_shape():
    analyses.save("One", "q1", a_real_turn())
    analyses.save("Two", "q2", a_real_turn())
    rows = analyses.list_all()
    assert [r["name"] for r in rows] == ["Two", "One"]   # newest first
    assert rows[0]["call_count"] == 1
    assert rows[0]["tools"] == ["get_market_size"]
    assert "envelope" not in str(rows)


def test_get_and_delete():
    saved = analyses.save("x", "q", a_real_turn())
    assert analyses.get(saved.id).question == "q"
    assert analyses.delete(saved.id) is True
    assert analyses.get(saved.id) is None
    assert analyses.delete(saved.id) is False


# ---------------------------------------------------------------------------
# The diff
# ---------------------------------------------------------------------------

def test_identical_results_produce_no_changes():
    before = [{"state": "Ohio", "dollar_sales": 100.0}]
    d = analyses.diff_rows(before, list(before))
    assert d["changed"] == [] and d["added"] == [] and d["removed"] == []
    assert d["unchanged_count"] == 1


def test_a_moved_number_is_reported_with_its_delta_and_percentage():
    before = [{"state": "Ohio", "dollar_sales": 100.0}]
    after = [{"state": "Ohio", "dollar_sales": 125.0}]
    field = analyses.diff_rows(before, after)["changed"][0]["fields"][0]
    assert field["column"] == "dollar_sales"
    assert field["before"] == 100.0 and field["after"] == 125.0
    assert field["delta"] == 25.0
    assert field["pct_change"] == pytest.approx(25.0)


def test_rows_are_keyed_by_their_non_numeric_columns_not_by_position():
    """Re-ordered results must not read as everything having changed."""
    before = [{"state": "Ohio", "v": 1.0}, {"state": "Maine", "v": 2.0}]
    after = [{"state": "Maine", "v": 2.0}, {"state": "Ohio", "v": 1.0}]
    d = analyses.diff_rows(before, after)
    assert d["changed"] == []
    assert d["unchanged_count"] == 2


def test_new_and_departed_rows_are_reported_separately():
    """This is the Arkansas case: a state that had no data now does."""
    before = [{"state": "Ohio", "v": 1.0}]
    after = [{"state": "Ohio", "v": 1.0}, {"state": "Arkansas", "v": 5.0}]
    d = analyses.diff_rows(before, after)
    assert [a["row"]["state"] for a in d["added"]] == ["Arkansas"]
    assert d["removed"] == []


def test_a_division_by_zero_baseline_does_not_crash_the_percentage():
    d = analyses.diff_rows([{"s": "x", "v": 0.0}], [{"s": "x", "v": 10.0}])
    field = d["changed"][0]["fields"][0]
    assert field["delta"] == 10.0
    assert field["pct_change"] is None


# ---------------------------------------------------------------------------
# Re-running
# ---------------------------------------------------------------------------

def test_rerunning_against_unchanged_data_shows_no_movement():
    saved = analyses.save("stable", "q", a_real_turn())
    result = analyses.rerun(saved.id)

    assert result["data_changed"] is False
    assert result["saved_fingerprint"] == result["current_fingerprint"]

    diff = result["results"][0]["diff"]
    assert diff["changed"] == []
    assert diff["added"] == [] and diff["removed"] == []
    assert diff["unchanged_count"] == 37


def test_rerunning_replays_the_saved_inputs_not_the_question():
    """The model is never consulted, so the comparison cannot drift."""
    saved = analyses.save("x", "a question that would be answered differently", a_real_turn())
    result = analyses.rerun(saved.id)
    assert result["results"][0]["tool_input"]["start_period"] == 2025
    assert result["results"][0]["tool_name"] == "get_market_size"


def test_a_detected_data_change_is_surfaced(monkeypatch):
    saved = analyses.save("x", "q", a_real_turn())

    # Pretend the data was reloaded since.
    monkeypatch.setattr(analyses, "get", lambda _id: _with_fingerprint(saved, "stale00000000"))
    result = analyses.rerun(saved.id)
    assert result["data_changed"] is True
    assert result["saved_fingerprint"] == "stale00000000"


def _with_fingerprint(saved, fp):
    saved.fingerprint = fp
    return saved


def test_rerunning_an_unknown_analysis_returns_none():
    assert analyses.rerun("nope") is None


def test_a_chart_spec_is_replayed_but_not_diffed():
    """render_chart returns a spec, not data -- diffing it is meaningless, and
    its reference to an earlier call must still resolve on replay."""
    calls = a_real_turn()
    calls.append({
        "tool_use_id": "toolu_2",
        "tool_name": "render_chart",
        "tool_input": {
            "type": "bar", "source_tool_call": "toolu_1", "x": "state",
            "y": "dollar_sales", "title": "t", "caption": "2025, 37 states",
        },
        "envelope": {},
    })
    saved = analyses.save("charted", "q", calls)
    result = analyses.rerun(saved.id)

    chart = result["results"][1]
    assert chart["tool_name"] == "render_chart"
    assert chart["diff"] is None
    # The reference resolved against the replayed toolu_1, so it did not error.
    assert chart["after"]["error"] is None
