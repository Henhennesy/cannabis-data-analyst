#!/usr/bin/env python3
"""Interactive CLI for the agent. Milestone 4 -- exercises the loop before any UI exists.

    python backend/cli.py
    python backend/cli.py --ask "What was the fast-acting share of edibles in 2025?"

Commands inside the REPL:
    /sql [n]    show the SQL for tool call n from the last turn (default: all)
    /rows n     show the first rows of tool call n
    /coverage   show coverage for every tool call in the last turn
    /usage      token usage for the last turn
    /reset      start a new conversation
    /quit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.app.agent import Agent, AgentEvent, Conversation  # noqa: E402
from backend.app.db import close_pool  # noqa: E402

DIM, RESET, BOLD = "\033[2m", "\033[0m", "\033[1m"
CYAN, YELLOW, RED, GREEN = "\033[36m", "\033[33m", "\033[31m", "\033[32m"


def _supports_colour() -> bool:
    return sys.stdout.isatty()


def c(code: str, text: str) -> str:
    return f"{code}{text}{RESET}" if _supports_colour() else text


class Session:
    def __init__(self) -> None:
        self.agent = Agent()
        self.convo = Conversation()
        self.last_usage: dict | None = None

    def ask(self, question: str) -> None:
        in_thinking = False
        in_text = False
        call_no = 0

        for ev in self.agent.run_turn(self.convo, question):
            if ev.type == "thinking":
                if not in_thinking:
                    print(c(DIM, "\n[thinking] "), end="", flush=True)
                    in_thinking = True
                print(c(DIM, ev.text), end="", flush=True)

            elif ev.type == "text":
                if in_thinking:
                    print()
                    in_thinking = False
                if not in_text:
                    print()
                    in_text = True
                print(ev.text, end="", flush=True)

            elif ev.type == "tool_call":
                in_thinking = in_text = False
                call_no += 1
                args = ", ".join(f"{k}={v!r}" for k, v in (ev.tool_input or {}).items())
                print(c(CYAN, f"\n  [{call_no}] -> {ev.tool_name}({args})"), flush=True)

            elif ev.type == "tool_result":
                env = ev.envelope
                if env is None:
                    continue
                if env.error:
                    print(c(RED, f"      !! {env.error}"), flush=True)
                else:
                    print(
                        c(DIM, f"      {env.row_count} row(s) from {env.relation} "
                               f"| {env.coverage.describe()}"),
                        flush=True,
                    )

            elif ev.type == "refusal":
                print(c(RED, f"\n{ev.text}"), flush=True)

            elif ev.type == "error":
                print(c(RED, f"\n[error] {ev.text}"), flush=True)

            elif ev.type == "turn_end":
                self.last_usage = ev.usage
                print()

    # -- inspector commands -------------------------------------------------

    def show_sql(self, which: str = "") -> None:
        envelopes = self.convo.envelopes_this_turn()
        if not envelopes:
            print(c(DIM, "no tool calls in the last turn"))
            return
        indices = range(len(envelopes))
        if which.strip():
            try:
                indices = [int(which) - 1]
            except ValueError:
                print(c(RED, "usage: /sql [n]"))
                return
        for i in indices:
            if not 0 <= i < len(envelopes):
                print(c(RED, f"no tool call {i + 1}"))
                continue
            env = envelopes[i]
            print(c(BOLD, f"\n--- [{i + 1}] {env.relation or 'n/a'} ---"))
            print(env.sql or "(no sql)")
            if env.params:
                print(c(DIM, f"params: {env.params}"))

    def show_rows(self, which: str) -> None:
        envelopes = self.convo.envelopes_this_turn()
        try:
            env = envelopes[int(which) - 1]
        except (ValueError, IndexError):
            print(c(RED, "usage: /rows n"))
            return
        print(c(BOLD, f"\n{env.row_count} row(s):"))
        for row in env.rows[:25]:
            print(f"  {row}")
        if env.row_count > 25:
            print(c(DIM, f"  ... {env.row_count - 25} more"))

    def show_coverage(self) -> None:
        for i, env in enumerate(self.convo.envelopes_this_turn(), 1):
            print(c(BOLD, f"[{i}] {env.coverage.describe()}"))
            for note in env.notes:
                print(c(DIM, f"    - {note}"))
            for caveat in env.coverage.caveats:
                print(c(YELLOW, f"    ! {caveat}"))

    def show_usage(self) -> None:
        if not self.last_usage:
            print(c(DIM, "no usage recorded"))
            return
        for k, v in self.last_usage.items():
            print(f"  {k}: {v:,}" if isinstance(v, int) else f"  {k}: {v}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ask", help="Ask one question and exit")
    args = ap.parse_args()

    try:
        session = Session()
    except RuntimeError as exc:
        print(c(RED, str(exc)), file=sys.stderr)
        return 2

    print(c(BOLD, "BDSA Market Intelligence Analyst"))
    print(c(DIM, f"model={session.agent.model} effort={session.agent.effort} "
                 f"max_tool_calls={session.agent.settings.max_tool_calls_per_turn}"))
    print(c(DIM, "/sql /rows /coverage /usage /reset /quit\n"))

    try:
        if args.ask:
            session.ask(args.ask)
            return 0

        while True:
            try:
                line = input(c(GREEN, "\n> ")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not line:
                continue
            if line in ("/quit", "/exit"):
                return 0
            if line == "/reset":
                session.convo = Conversation()
                print(c(DIM, "conversation cleared"))
                continue
            if line.startswith("/sql"):
                session.show_sql(line[4:])
                continue
            if line.startswith("/rows"):
                session.show_rows(line[5:].strip())
                continue
            if line == "/coverage":
                session.show_coverage()
                continue
            if line == "/usage":
                session.show_usage()
                continue
            if line.startswith("/"):
                print(c(RED, f"unknown command {line.split()[0]}"))
                continue
            session.ask(line)
    finally:
        close_pool()


if __name__ == "__main__":
    raise SystemExit(main())
