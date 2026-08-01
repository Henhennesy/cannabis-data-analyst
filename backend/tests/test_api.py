"""FastAPI chat endpoint and SSE streaming.

The agent is stubbed here. What matters at this layer is the wire contract --
event framing, envelope fidelity, conversation continuity, and that a mid-stream
failure reaches the client instead of becoming a dead connection.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.agent import AgentEvent
from backend.app.envelope import Coverage, ToolEnvelope


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c
    main._conversations.clear()


def sse_events(response) -> list[dict]:
    """Parse an SSE body into event dicts."""
    out = []
    for block in response.text.split("\n\n"):
        block = block.strip()
        if block.startswith("data: "):
            out.append(json.loads(block[len("data: "):]))
    return out


class _StubAgent:
    """Returns a fixed event sequence, ignoring the message."""

    events: list[AgentEvent] = []
    raise_on_turn: Exception | None = None
    seen_messages: list[str] = []

    def __init__(self):
        pass

    def run_turn(self, convo, user_message):
        type(self).seen_messages.append(user_message)
        convo.add_user(user_message)
        if type(self).raise_on_turn is not None:
            raise type(self).raise_on_turn
        yield from type(self).events


@pytest.fixture(autouse=True)
def stub_agent(monkeypatch):
    _StubAgent.events = [AgentEvent(type="turn_end", stop_reason="end_turn", usage={})]
    _StubAgent.raise_on_turn = None
    _StubAgent.seen_messages = []
    monkeypatch.setattr(main, "Agent", _StubAgent)
    yield


# ---------------------------------------------------------------------------

def test_health_reports_configuration_without_leaking_secrets(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["model"]
    assert isinstance(body["anthropic_configured"], bool)
    # Never echo the credentials themselves.
    assert "sk-ant" not in json.dumps(body)
    assert "postgres" not in json.dumps(body).lower()


def test_chat_streams_sse_and_brackets_the_turn(client):
    _StubAgent.events = [
        AgentEvent(type="text", text="Edibles were "),
        AgentEvent(type="text", text="$3.87B."),
        AgentEvent(type="turn_end", stop_reason="end_turn", usage={"output_tokens": 12}),
    ]
    r = client.post("/api/chat", json={"message": "how big?"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    events = sse_events(r)
    assert events[0]["type"] == "start"
    assert events[0]["conversation_id"]
    assert events[-1]["type"] == "done"
    assert "".join(e.get("text", "") for e in events if e["type"] == "text") \
        == "Edibles were $3.87B."


def test_tool_events_carry_the_full_envelope_not_the_model_view(client):
    """The browser renders charts and tables, so it needs every row -- the
    truncation to 40 rows applies only to what the model sees."""
    envelope = ToolEnvelope(
        rows=[{"state": f"S{i}", "dollar_sales": float(i)} for i in range(300)],
        row_count=300,
        sql="SELECT state, sum(total_sales) FROM ...",
        params={"y0": 2025},
        coverage=Coverage(period_start=2025, period_end=2025, states=["Ohio"]),
        relation="mv_category_monthly",
    )
    _StubAgent.events = [
        AgentEvent(type="tool_call", tool_name="get_market_size",
                   tool_use_id="toolu_9", tool_input={"metric": "dollar_sales"}),
        AgentEvent(type="tool_result", tool_name="get_market_size",
                   tool_use_id="toolu_9", envelope=envelope),
        AgentEvent(type="turn_end", stop_reason="end_turn"),
    ]
    events = sse_events(client.post("/api/chat", json={"message": "x"}))

    call = next(e for e in events if e["type"] == "tool_call")
    assert call["tool_name"] == "get_market_size"
    assert call["tool_input"] == {"metric": "dollar_sales"}

    result = next(e for e in events if e["type"] == "tool_result")
    env = result["envelope"]
    assert len(env["rows"]) == 300            # every row, not the model's 40
    assert env["sql"].startswith("SELECT")    # auditable
    assert env["params"] == {"y0": 2025}
    assert env["coverage"]["period_start"] == 2025


def test_conversation_id_is_returned_and_reused(client):
    first = sse_events(client.post("/api/chat", json={"message": "one"}))
    cid = first[0]["conversation_id"]

    second = sse_events(
        client.post("/api/chat", json={"message": "two", "conversation_id": cid})
    )
    assert second[0]["conversation_id"] == cid

    # Both turns landed in the same history.
    convo = main._conversations[cid]
    assert [m["content"] for m in convo.messages if m["role"] == "user"] == ["one", "two"]


def test_an_unknown_conversation_id_starts_a_fresh_conversation(client):
    events = sse_events(
        client.post("/api/chat", json={"message": "hi", "conversation_id": "nope123"})
    )
    assert events[0]["conversation_id"] == "nope123"
    assert "nope123" in main._conversations


def test_a_mid_stream_failure_reaches_the_client_and_still_closes(client):
    """A turn that blows up must not leave the UI waiting forever."""
    _StubAgent.raise_on_turn = RuntimeError("neon went away")
    events = sse_events(client.post("/api/chat", json={"message": "x"}))
    error = next(e for e in events if e["type"] == "error")
    assert "neon went away" in error["text"]
    assert events[-1]["type"] == "done"


def test_refusal_is_streamed_as_its_own_event_type(client):
    _StubAgent.events = [
        AgentEvent(type="refusal", text="The model declined this request.",
                   stop_reason="refusal"),
    ]
    events = sse_events(client.post("/api/chat", json={"message": "x"}))
    assert any(e["type"] == "refusal" for e in events)
    assert events[-1]["type"] == "done"


def test_empty_message_is_rejected(client):
    assert client.post("/api/chat", json={"message": ""}).status_code == 422


def test_streaming_headers_defeat_proxy_buffering(client):
    """Caddy and most proxies buffer by default, which silently turns a live
    stream into one delayed blob."""
    r = client.post("/api/chat", json={"message": "x"})
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-accel-buffering"] == "no"


@pytest.mark.db
def test_coverage_endpoint_feeds_the_banner(client):
    body = client.get("/api/coverage").json()
    assert body["period_start"] == 2025
    assert body["period_end"] == 2026
    assert body["state_count"] == 37
    assert body["partial_periods"] == [2026]
    assert any("PARTIAL" in c for c in body["caveats"])
