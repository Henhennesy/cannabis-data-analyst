"""The tool-use loop and conversation state.

Streams structured events so a caller (CLI now, SSE later) can show which tools
are firing while the turn is still running.

Model configuration notes, because several of these will 400 if got wrong on
Opus 5:

* `temperature` / `top_p` / `top_k` are REMOVED on this model family. The
  instinct for a "never invent a number" application is to set temperature=0
  for determinism; that returns a 400. Determinism comes from the tools, not
  from sampling parameters.
* `thinking.budget_tokens` is removed. Depth is controlled by
  `output_config.effort`.
* Thinking is ON by default on Opus 5. `display` defaults to "omitted", which
  streams empty thinking blocks -- we ask for "summarized" so the reasoning is
  visible in the inspector alongside the SQL.
* `max_tokens` caps thinking AND response text together, so it needs headroom.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Literal

import anthropic

from .config import REPO_ROOT, get_settings
from .envelope import ToolEnvelope
from .tools import registry

log = logging.getLogger(__name__)

SYSTEM_PROMPT_PATH = REPO_ROOT / "backend" / "app" / "prompts" / "system.md"

# Generous: max_tokens bounds thinking + text together on Opus 5, and an
# agentic turn with several tool calls can think a lot before answering.
MAX_TOKENS = 32_000

EventType = Literal[
    "thinking", "text", "tool_call", "tool_result", "turn_end", "error", "refusal"
]


@dataclass
class AgentEvent:
    type: EventType
    text: str = ""
    tool_name: str | None = None
    tool_use_id: str | None = None
    tool_input: dict[str, Any] | None = None
    envelope: ToolEnvelope | None = None
    stop_reason: str | None = None
    usage: dict[str, Any] | None = None


def load_system_prompt() -> str:
    """Read from disk on every turn.

    Deliberate: the prompt is the product's core behaviour spec, and being able
    to edit it and see the effect on the next turn without a restart is worth
    far more than the microseconds saved by caching it in memory.
    """
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


@dataclass
class Conversation:
    """Message history plus the tool results produced during it.

    `tool_results` retains the FULL envelopes, keyed by tool_use_id. The model
    only ever saw a truncated view (see ToolEnvelope.for_model), so this is the
    authoritative record -- it is what the inspector displays and what a chart
    will later render against.
    """

    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_results: dict[str, ToolEnvelope] = field(default_factory=dict)
    turn_tool_use_ids: list[str] = field(default_factory=list)

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def envelopes_this_turn(self) -> list[ToolEnvelope]:
        return [self.tool_results[i] for i in self.turn_tool_use_ids
                if i in self.tool_results]


class Agent:
    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        s = get_settings()
        if not s.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")
        self.settings = s
        self.client = client or anthropic.Anthropic(api_key=s.anthropic_api_key)
        self.model = s.model
        self.effort = s.effort

    def run_turn(self, convo: Conversation, user_message: str) -> Iterator[AgentEvent]:
        """Run one user turn to completion, yielding events as they happen."""
        convo.add_user(user_message)
        convo.turn_tool_use_ids = []

        system = [{
            "type": "text",
            "text": load_system_prompt(),
            # Tools render before system, so this one breakpoint caches the
            # tool schemas and the system prompt together.
            "cache_control": {"type": "ephemeral"},
        }]
        tools = registry.anthropic_tool_schemas()

        for call_index in range(self.settings.max_tool_calls_per_turn + 1):
            try:
                message, events = self._one_exchange(convo, system, tools)
            except anthropic.APIStatusError as exc:
                yield AgentEvent(type="error", text=f"API error {exc.status_code}: {exc.message}")
                return
            except anthropic.APIConnectionError as exc:
                yield AgentEvent(type="error", text=f"Connection error: {exc}")
                return

            yield from events

            # Check refusal BEFORE reading content: on a refusal `content` is
            # empty or partial, and treating it as a normal answer would present
            # a truncated response as complete.
            if message.stop_reason == "refusal":
                detail = getattr(message, "stop_details", None)
                category = getattr(detail, "category", None) if detail else None
                yield AgentEvent(
                    type="refusal",
                    text=f"The model declined this request"
                         + (f" (category: {category})" if category else "")
                         + ". No answer was produced.",
                    stop_reason="refusal",
                )
                return

            convo.messages.append({"role": "assistant", "content": message.content})

            tool_uses = [b for b in message.content if b.type == "tool_use"]
            if not tool_uses:
                yield AgentEvent(
                    type="turn_end",
                    stop_reason=message.stop_reason,
                    usage=_usage(message),
                )
                return

            if call_index >= self.settings.max_tool_calls_per_turn:
                # Budget exhausted. Every tool_use still needs a result or the
                # conversation is malformed, so answer them all with an error.
                results = [
                    _error_result(
                        b.id,
                        f"Tool-call budget of {self.settings.max_tool_calls_per_turn} "
                        f"exhausted for this turn. Answer with what you have, or tell "
                        f"the user the question needs to be narrowed.",
                    )
                    for b in tool_uses
                ]
                convo.messages.append({"role": "user", "content": results})
                yield AgentEvent(
                    type="error",
                    text=f"Reached the {self.settings.max_tool_calls_per_turn}-tool-call "
                         f"limit for this turn.",
                )
                continue

            results = []
            for block in tool_uses:
                raw_input = dict(block.input) if block.input else {}
                yield AgentEvent(
                    type="tool_call",
                    tool_name=block.name,
                    tool_use_id=block.id,
                    tool_input=raw_input,
                )

                envelope = registry.dispatch(block.name, raw_input)
                convo.tool_results[block.id] = envelope
                convo.turn_tool_use_ids.append(block.id)

                yield AgentEvent(
                    type="tool_result",
                    tool_name=block.name,
                    tool_use_id=block.id,
                    envelope=envelope,
                )

                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(envelope.for_model(), default=str),
                    "is_error": envelope.error is not None,
                })

            # All results for one assistant turn go back in ONE user message.
            # Splitting them trains the model out of parallel tool calls.
            convo.messages.append({"role": "user", "content": results})

    def _one_exchange(self, convo, system, tools):
        """One request/response. Returns (final message, events emitted)."""
        events: list[AgentEvent] = []
        with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=tools,
            messages=convo.messages,
            # Adaptive is the default on Opus 5; "summarized" opts back into
            # visible reasoning (the default omits the text entirely).
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": self.effort},
            # A policy decline would otherwise just stop the turn. "default"
            # routes by refusal category rather than pinning a model.
            fallbacks="default",
            betas=["server-side-fallback-2026-07-01"],
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        events.append(AgentEvent(type="text", text=event.delta.text))
                    elif event.delta.type == "thinking_delta":
                        events.append(AgentEvent(type="thinking", text=event.delta.thinking))
            message = stream.get_final_message()
        return message, events


def _error_result(tool_use_id: str, message: str) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps({"error": message}),
        "is_error": True,
    }


def _usage(message) -> dict[str, Any]:
    u = getattr(message, "usage", None)
    if u is None:
        return {}
    return {
        "input_tokens": getattr(u, "input_tokens", None),
        "output_tokens": getattr(u, "output_tokens", None),
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", None),
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", None),
    }
