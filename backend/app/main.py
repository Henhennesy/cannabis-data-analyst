"""FastAPI app: chat endpoint with SSE streaming, plus coverage for the banner.

Streaming shape: POST /api/chat returns `text/event-stream`. It is a POST rather
than the usual EventSource GET because the question goes in the body, and
EventSource cannot POST. The client reads the response with a stream reader.

Every event carries the FULL tool envelope, including all rows. The model only
ever saw a truncated view; the browser gets the real thing, because it is the
browser that renders charts and tables against it. That asymmetry is the chart
contract: the model names a tool call, it never transcribes numbers.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from contextlib import asynccontextmanager
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .agent import Agent, Conversation
from .db import close_pool
from .tools import DescribeCoverageInput, describe_coverage

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    close_pool()


app = FastAPI(
    title="BDSA Market Intelligence Analyst", version="0.1.0", lifespan=lifespan
)

# Dev only: Vite serves the UI on 5173 while the API is on 8000. In deployment
# Caddy fronts both on one origin and this is inert.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Conversation store
# ---------------------------------------------------------------------------
# In-process and non-durable on purpose. This is a single-user desktop tool, and
# durable analyses are Milestone 8 (saved analyses, on disk). Keeping it here
# would be wrong for multi-user, which is an explicit non-goal.

_conversations: dict[str, Conversation] = {}
_lock = threading.Lock()


def _get_conversation(conversation_id: str | None) -> tuple[str, Conversation]:
    with _lock:
        if conversation_id and conversation_id in _conversations:
            return conversation_id, _conversations[conversation_id]
        new_id = conversation_id or uuid.uuid4().hex[:12]
        convo = Conversation()
        _conversations[new_id] = convo
        return new_id, convo


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@app.post("/api/chat")
def chat(req: ChatRequest) -> StreamingResponse:
    conversation_id, convo = _get_conversation(req.conversation_id)

    try:
        agent = Agent()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    def event_stream() -> Iterator[str]:
        yield _sse({"type": "start", "conversation_id": conversation_id})
        try:
            for ev in agent.run_turn(convo, req.message):
                payload: dict[str, Any] = {"type": ev.type}
                if ev.text:
                    payload["text"] = ev.text
                if ev.tool_name:
                    payload["tool_name"] = ev.tool_name
                if ev.tool_use_id:
                    payload["tool_use_id"] = ev.tool_use_id
                if ev.tool_input is not None:
                    payload["tool_input"] = ev.tool_input
                if ev.envelope is not None:
                    # Full envelope: rows, sql, params, coverage. The inspector
                    # and the chart canvas both read from this.
                    payload["envelope"] = ev.envelope.model_dump()
                if ev.stop_reason:
                    payload["stop_reason"] = ev.stop_reason
                if ev.usage:
                    payload["usage"] = ev.usage
                if ev.figures is not None:
                    payload["figures"] = ev.figures
                yield _sse(payload)
        except Exception as exc:  # noqa: BLE001 - must reach the client, not a 500 mid-stream
            log.exception("chat turn failed")
            yield _sse({"type": "error", "text": f"{type(exc).__name__}: {exc}"})
        finally:
            # The client waits on this; without it a dropped turn hangs the UI.
            yield _sse({"type": "done"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Caddy and most proxies buffer by default, which defeats streaming.
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/coverage")
def coverage() -> dict[str, Any]:
    """Feeds the always-on coverage banner.

    Cheap enough to call on page load: describe_coverage is cached on the
    dataset fingerprint and measures ~0.09s cold.
    """
    env = describe_coverage(DescribeCoverageInput())
    if env.error:
        raise HTTPException(status_code=503, detail=env.error)
    return {
        "period_start": env.coverage.period_start,
        "period_end": env.coverage.period_end,
        "states": env.coverage.states,
        "state_count": len(env.coverage.states),
        "partial_periods": env.coverage.partial_periods,
        "caveats": env.coverage.caveats,
        "notes": env.notes,
        "rows": env.rows,
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    from .config import get_settings
    s = get_settings()
    return {
        "ok": True,
        "model": s.model,
        "effort": s.effort,
        "max_tool_calls_per_turn": s.max_tool_calls_per_turn,
        "statement_timeout_ms": s.statement_timeout_ms,
        "database_configured": bool(s.readonly_url),
        "anthropic_configured": s.anthropic_api_key.startswith("sk-ant-"),
    }
