import { useCallback, useEffect, useRef, useState } from "react";
import "./App.css";
import { CoverageBanner } from "./components/CoverageBanner";
import { TurnView } from "./components/TurnView";
import { streamChat } from "./lib/api";
import type { StreamEvent, ToolCall, Turn } from "./lib/types";

const EXAMPLES = [
  "What was the fast-acting share of the national edibles market in 2025, in dollars?",
  "Which five states had the largest edibles market in 2025?",
  "Compare edibles sales in 2025 versus 2026.",
];

export default function App() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const conversationId = useRef<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);

  // Follow the stream, but only while the user is already near the bottom --
  // yanking the viewport away from something they are reading is worse than
  // not following at all.
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 200;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }, [turns]);

  const ask = useCallback(
    async (question: string) => {
      const q = question.trim();
      if (!q || busy) return;

      setBusy(true);
      setDraft("");
      setTurns((prev) => [
        ...prev,
        { question: q, thinking: "", answer: "", toolCalls: [], status: "streaming" },
      ]);

      // Mutate only the last turn; every update is a fresh object so React sees it.
      const patch = (fn: (t: Turn) => Turn) =>
        setTurns((prev) => {
          const next = [...prev];
          next[next.length - 1] = fn(next[next.length - 1]);
          return next;
        });

      const onEvent = (e: StreamEvent) => {
        switch (e.type) {
          case "start":
            conversationId.current = e.conversation_id;
            break;
          case "thinking":
            patch((t) => ({ ...t, thinking: t.thinking + e.text }));
            break;
          case "text":
            patch((t) => ({ ...t, answer: t.answer + e.text }));
            break;
          case "tool_call": {
            const call: ToolCall = {
              id: e.tool_use_id,
              name: e.tool_name,
              input: e.tool_input,
            };
            patch((t) => ({ ...t, toolCalls: [...t.toolCalls, call] }));
            break;
          }
          case "tool_result":
            patch((t) => ({
              ...t,
              toolCalls: t.toolCalls.map((c) =>
                c.id === e.tool_use_id ? { ...c, envelope: e.envelope } : c,
              ),
            }));
            break;
          case "refusal":
            patch((t) => ({ ...t, status: "refused", notice: e.text }));
            break;
          case "error":
            patch((t) => ({ ...t, status: "error", notice: e.text }));
            break;
          case "turn_end":
            patch((t) => ({
              ...t,
              status: t.status === "streaming" ? "done" : t.status,
              usage: e.usage,
            }));
            break;
          case "done":
            break;
        }
      };

      try {
        await streamChat(q, conversationId.current, onEvent);
      } catch (err) {
        patch((t) => ({
          ...t,
          status: "error",
          notice: err instanceof Error ? err.message : String(err),
        }));
      } finally {
        setBusy(false);
        textarea.current?.focus();
      }
    },
    [busy],
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends; Shift+Enter is a newline. Standard for a chat composer.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void ask(draft);
    }
  };

  return (
    <div className="app">
      <CoverageBanner />

      <div className="conversation" ref={scroller}>
        <div className="thread">
          {turns.length === 0 ? (
            <div className="empty">
              <h1>BDSA Market Intelligence</h1>
              <p>
                Every figure comes from a query against the database, and the
                exact SQL behind it is one click away. Nothing is estimated.
              </p>
              <ul>
                {EXAMPLES.map((ex) => (
                  <li key={ex}>
                    <button onClick={() => void ask(ex)}>{ex}</button>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            turns.map((t, i) => <TurnView key={i} turn={t} />)
          )}
        </div>
      </div>

      <div className="composer">
        <div className="composer__inner">
          <textarea
            ref={textarea}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask about category size, brand share, segment penetration…"
            rows={1}
            disabled={busy}
            aria-label="Question"
          />
          <button onClick={() => void ask(draft)} disabled={busy || !draft.trim()}>
            {busy ? "…" : "Ask"}
          </button>
        </div>
        <div className="composer__hint">
          Enter to send · Shift+Enter for a newline · click any tool call to see
          its SQL
        </div>
      </div>

      <div className="sr-only" role="status" aria-live="polite">
        {busy ? "Working" : "Ready"}
      </div>
    </div>
  );
}
