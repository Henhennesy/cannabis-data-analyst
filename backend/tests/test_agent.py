"""Agent loop and tool registry.

The loop is tested against a stub client rather than the live API: the things
that must be right here — every tool_use gets a tool_result, the call budget is
enforced, a refusal is never read as an answer — are control-flow properties,
and asserting them against a real model would be slow, costly, and
non-deterministic. A live smoke test is in test_agent_live.py.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.app import agent as agent_module
from backend.app.agent import Agent, Conversation
from backend.app.envelope import Coverage, ToolEnvelope
from backend.app.tools import registry


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_every_tool_has_a_well_formed_schema():
    for tool in registry.TOOLS:
        assert tool.schema["name"] == tool.name
        assert tool.schema["description"].strip()
        assert tool.schema["input_schema"]["type"] == "object"


def test_tool_order_is_stable():
    """Tool definitions render before the system prompt. Reordering them
    changes the cached prefix and invalidates the prompt cache.

    Discovery tools first, so the model reads "check before you filter" at the
    top of its list; run_sql last, because it is the escape hatch.
    """
    assert [t.name for t in registry.TOOLS] == [
        "describe_coverage",
        "list_dimension_values",
        "get_market_size",
        "get_segment_penetration",
        "get_brand_share",
        "run_sql",
    ]


def test_unknown_tool_returns_an_envelope_not_an_exception():
    env = registry.dispatch("get_the_answer", {})
    assert env.error is not None
    assert "Unknown tool" in env.error


def test_invalid_arguments_return_a_readable_error():
    env = registry.dispatch("get_market_size", {"metric": "revenue",
                                                "start_period": 2025,
                                                "end_period": 2025})
    assert env.error is not None
    assert "metric" in env.error


def test_handler_exceptions_are_captured_as_envelopes(monkeypatch):
    """A tool that raises must still produce a result the model can read --
    a missing tool_result would break the conversation outright."""
    def boom(_):
        raise RuntimeError("database on fire")

    monkeypatch.setitem(
        registry.BY_NAME, "describe_coverage",
        registry.RegisteredTool(
            name="describe_coverage",
            schema=registry.BY_NAME["describe_coverage"].schema,
            input_model=registry.BY_NAME["describe_coverage"].input_model,
            handler=boom,
        ),
    )
    env = registry.dispatch("describe_coverage", {})
    assert env.error is not None
    assert "database on fire" in env.error


# ---------------------------------------------------------------------------
# Model-facing envelope view
# ---------------------------------------------------------------------------

def test_for_model_truncates_rows_but_never_the_row_count():
    env = ToolEnvelope(
        rows=[{"state": f"S{i}", "dollar_sales": i} for i in range(500)],
        row_count=500,
        sql="SELECT ...",
        coverage=Coverage(period_start=2025, period_end=2025, states=["Ohio"]),
    )
    view = env.for_model(max_rows=10)
    assert len(view["rows"]) == 10
    assert view["row_count"] == 500          # the TRUE count, never the shown count
    assert "40" not in str(view["rows_shown"])
    assert "Do not describe the unshown rows" in view["note_on_rows"]


def test_for_model_carries_caveats_and_omits_rows_on_error():
    env = ToolEnvelope.failed("period outside coverage")
    view = env.for_model()
    assert view["error"] == "period outside coverage"
    assert view["rows"] == []


def test_for_model_summarises_a_long_state_list():
    env = ToolEnvelope(
        rows=[], row_count=0,
        coverage=Coverage(states=[f"State{i}" for i in range(37)]),
    )
    view = env.for_model()
    assert view["coverage"]["state_count"] == 37
    assert len(view["coverage"]["states"]) == 13  # 12 + truncation marker


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

class _StubStream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(())

    def get_final_message(self):
        return self._message


class _StubMessages:
    def __init__(self, messages):
        self._queue = list(messages)
        self.calls: list[dict] = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        msg = self._queue.pop(0) if self._queue else _text_message("done")
        return _StubStream(msg)


class _StubClient:
    def __init__(self, messages):
        self.beta = SimpleNamespace(messages=_StubMessages(messages))


def _text_message(text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=10, output_tokens=5,
                              cache_read_input_tokens=0,
                              cache_creation_input_tokens=0),
    )


def _tool_message(name: str, tool_input: dict, use_id: str = "toolu_1"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", id=use_id, name=name, input=tool_input)],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5,
                              cache_read_input_tokens=0,
                              cache_creation_input_tokens=0),
    )


@pytest.fixture
def stub_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    from backend.app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_a_plain_answer_ends_the_turn(stub_settings):
    client = _StubClient([_text_message("Edibles were $3.87B in 2025.")])
    a = Agent(client=client)
    convo = Conversation()
    events = list(a.run_turn(convo, "How big were edibles?"))
    assert [e.type for e in events] == ["turn_end"]
    assert events[-1].stop_reason == "end_turn"


def test_a_tool_call_is_dispatched_and_answered(stub_settings, monkeypatch):
    monkeypatch.setitem(
        registry.BY_NAME, "describe_coverage",
        registry.RegisteredTool(
            name="describe_coverage",
            schema=registry.BY_NAME["describe_coverage"].schema,
            input_model=registry.BY_NAME["describe_coverage"].input_model,
            handler=lambda _: ToolEnvelope(rows=[{"ok": 1}], row_count=1, sql="SELECT 1"),
        ),
    )
    client = _StubClient([
        _tool_message("describe_coverage", {}),
        _text_message("2025 and 2026 are loaded."),
    ])
    a = Agent(client=client)
    convo = Conversation()
    types = [e.type for e in a.run_turn(convo, "what's loaded?")]
    assert types == ["tool_call", "tool_result", "turn_end"]

    # The full envelope is retained server-side, keyed by tool_use_id.
    assert convo.tool_results["toolu_1"].row_count == 1
    assert convo.turn_tool_use_ids == ["toolu_1"]


def test_the_tool_call_budget_is_enforced(stub_settings, monkeypatch):
    """A model that keeps calling tools must be stopped, and every tool_use
    still needs a matching tool_result or the conversation is malformed."""
    monkeypatch.setenv("MAX_TOOL_CALLS_PER_TURN", "3")
    from backend.app.config import get_settings
    get_settings.cache_clear()

    monkeypatch.setitem(
        registry.BY_NAME, "describe_coverage",
        registry.RegisteredTool(
            name="describe_coverage",
            schema=registry.BY_NAME["describe_coverage"].schema,
            input_model=registry.BY_NAME["describe_coverage"].input_model,
            handler=lambda _: ToolEnvelope(rows=[], row_count=0),
        ),
    )
    # Always asks for another tool -- never answers.
    client = _StubClient([_tool_message("describe_coverage", {}, f"toolu_{i}")
                          for i in range(10)])
    a = Agent(client=client)
    convo = Conversation()
    events = list(a.run_turn(convo, "loop forever"))

    assert sum(1 for e in events if e.type == "tool_call") == 3
    assert any(e.type == "error" and "limit" in e.text for e in events)

    # Every tool_use block has a matching tool_result.
    tool_use_ids, result_ids = set(), set()
    for msg in convo.messages:
        content = msg["content"]
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                result_ids.add(block["tool_use_id"])
            elif getattr(block, "type", None) == "tool_use":
                tool_use_ids.add(block.id)
    assert tool_use_ids == result_ids


def test_a_refusal_is_never_read_as_an_answer(stub_settings):
    refused = SimpleNamespace(
        content=[],
        stop_reason="refusal",
        stop_details=SimpleNamespace(category="cyber", explanation="declined"),
        usage=SimpleNamespace(input_tokens=1, output_tokens=0,
                              cache_read_input_tokens=0,
                              cache_creation_input_tokens=0),
    )
    a = Agent(client=_StubClient([refused]))
    convo = Conversation()
    events = list(a.run_turn(convo, "..."))
    assert events[0].type == "refusal"
    assert "cyber" in events[0].text
    # Nothing was appended as if it were a real assistant answer.
    assert all(m["role"] != "assistant" for m in convo.messages)


def test_request_omits_parameters_that_400_on_this_model(stub_settings):
    """temperature/top_p/top_k and budget_tokens are removed on Opus 5.

    The instinct for a 'never invent a number' app is temperature=0 for
    determinism; that returns a 400 here.
    """
    client = _StubClient([_text_message("hi")])
    a = Agent(client=client)
    list(a.run_turn(Conversation(), "hi"))
    kwargs = client.beta.messages.calls[0]
    for banned in ("temperature", "top_p", "top_k"):
        assert banned not in kwargs
    assert "budget_tokens" not in kwargs["thinking"]
    assert kwargs["thinking"]["type"] == "adaptive"
    assert kwargs["output_config"]["effort"] == a.effort


def test_system_prompt_is_cached_and_tools_precede_it(stub_settings):
    client = _StubClient([_text_message("hi")])
    a = Agent(client=client)
    list(a.run_turn(Conversation(), "hi"))
    kwargs = client.beta.messages.calls[0]
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert [t["name"] for t in kwargs["tools"]] == [t.name for t in registry.TOOLS]


# ---------------------------------------------------------------------------
# The system prompt is behaviour, so assert on its content
# ---------------------------------------------------------------------------

def test_system_prompt_states_the_non_negotiable_rules():
    text = agent_module.load_system_prompt()
    assert "Never state a figure you did not retrieve" in text
    for required in [
        "category_l2 = 'Edibles'",       # nesting
        "Inhaleables",                    # spelling
        "if and only if",                 # fast_acting biconditional
        "sell-through",                   # not total market
        "Refuse bare year-over-year",     # the agreed refusal
        "list_dimension_values",          # confirm filters first
        "describe_coverage",              # check coverage first
    ]:
        assert required in text, f"system prompt is missing: {required}"


def test_system_prompt_is_read_from_disk_each_turn(tmp_path, monkeypatch):
    """Editing the prompt must take effect on the next turn without a restart."""
    p = tmp_path / "system.md"
    p.write_text("VERSION ONE", encoding="utf-8")
    monkeypatch.setattr(agent_module, "SYSTEM_PROMPT_PATH", p)
    assert agent_module.load_system_prompt() == "VERSION ONE"
    p.write_text("VERSION TWO", encoding="utf-8")
    assert agent_module.load_system_prompt() == "VERSION TWO"
