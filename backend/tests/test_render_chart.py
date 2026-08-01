"""The chart contract.

The model never supplies data points -- it names a prior tool call and columns.
Everything here exists to make a chart that misrepresents its source
impossible to produce.
"""

from __future__ import annotations

from backend.app.envelope import Coverage, ToolEnvelope
from backend.app.tools import registry
from backend.app.tools.render_chart import RenderChartInput, render_chart


def source_env(rows=None, **kw):
    return ToolEnvelope(
        rows=rows if rows is not None else [
            {"state": "California", "dollar_sales": 700_200_580.23},
            {"state": "Michigan", "dollar_sales": 328_864_846.35},
        ],
        row_count=kw.pop("row_count", 2),
        coverage=Coverage(
            period_start=2025, period_end=2025,
            states=["California", "Michigan"], partial_periods=[],
        ),
        **kw,
    )


def spec(**kw):
    base = dict(
        type="bar", source_tool_call="toolu_1", x="state",
        y="dollar_sales", title="Edibles by state", caption="2025, 37 states",
    )
    base.update(kw)
    return RenderChartInput(**base)


def test_a_valid_spec_is_accepted_and_carries_no_data_points():
    env = render_chart(spec(), {"toolu_1": source_env()})
    assert env.error is None
    payload = env.rows[0]
    assert payload["x"] == "state" and payload["y"] == "dollar_sales"
    # The spec names columns; it must not embed values.
    assert "700200580" not in str(payload)
    assert "rows" not in payload


def test_the_chart_inherits_its_sources_coverage():
    """A chart labelled with a different period than its data would be a lie."""
    env = render_chart(spec(), {"toolu_1": source_env()})
    assert env.coverage.period_start == 2025
    assert env.coverage.states == ["California", "Michigan"]


def test_referencing_a_tool_call_that_does_not_exist_is_rejected():
    env = render_chart(spec(source_tool_call="toolu_99"), {"toolu_1": source_env()})
    assert env.error is not None
    assert "toolu_99" in env.error
    assert "toolu_1" in env.error  # tells the model what IS available


def test_a_column_that_does_not_exist_is_rejected_with_the_real_columns_listed():
    env = render_chart(spec(y="revenue"), {"toolu_1": source_env()})
    assert env.error is not None
    assert "revenue" in env.error
    assert "dollar_sales" in env.error


def test_a_bad_series_column_is_also_caught():
    env = render_chart(spec(series="segment"), {"toolu_1": source_env()})
    assert env.error is not None
    assert "segment" in env.error


def test_a_non_numeric_value_axis_is_rejected_unless_it_is_a_table():
    results = {"toolu_1": source_env()}
    assert render_chart(spec(y="state"), results).error is not None
    assert render_chart(spec(type="table", y="state"), results).error is None


def test_charting_a_failed_tool_call_is_rejected():
    failed = ToolEnvelope.failed("period outside coverage")
    env = render_chart(spec(), {"toolu_1": failed})
    assert env.error is not None
    assert "nothing to plot" in env.error


def test_charting_an_empty_result_is_rejected_because_it_implies_a_zero_market():
    empty = source_env(rows=[], row_count=0)
    env = render_chart(spec(), {"toolu_1": empty})
    assert env.error is not None
    assert "zero market" in env.error


def test_a_truncated_source_is_flagged_in_the_notes():
    env = render_chart(spec(), {"toolu_1": source_env(truncated=True)})
    assert env.error is None
    assert any("TRUNCATED" in n for n in env.notes)


def test_the_notes_discourage_restating_the_numbers_in_prose():
    """The whole point is that the chart is the source of the figures."""
    env = render_chart(spec(), {"toolu_1": source_env()})
    assert any("do not restate those numbers" in n for n in env.notes)


def test_the_registry_passes_turn_results_to_render_chart_only():
    """Dispatch must supply context to render_chart and not break the others."""
    assert registry.BY_NAME["render_chart"].needs_turn_results is True
    assert registry.BY_NAME["get_market_size"].needs_turn_results is False

    env = registry.dispatch(
        "render_chart",
        {"type": "bar", "source_tool_call": "toolu_1", "x": "state",
         "y": "dollar_sales", "title": "t", "caption": "c"},
        turn_results={"toolu_1": source_env()},
    )
    assert env.error is None


def test_dispatch_without_context_gives_a_readable_error_not_a_crash():
    env = registry.dispatch(
        "render_chart",
        {"type": "bar", "source_tool_call": "toolu_1", "x": "state",
         "y": "dollar_sales", "title": "t", "caption": "c"},
    )
    assert env.error is not None
    assert "none yet" in env.error
