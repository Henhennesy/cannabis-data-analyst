import type { Turn } from "../lib/types";
import { Answer } from "./Answer";
import { ToolCallRow } from "./ToolCallRow";

export function TurnView({ turn }: { turn: Turn }) {
  return (
    <article className="turn">
      <div className="turn__question">{turn.question}</div>

      {turn.thinking && (
        <details className="thinking">
          <summary>reasoning</summary>
          <div className="thinking__body">{turn.thinking}</div>
        </details>
      )}

      {turn.toolCalls.length > 0 && (
        <div className="tools">
          {turn.toolCalls.map((call, i) => (
            <ToolCallRow key={call.id} call={call} index={i + 1} />
          ))}
        </div>
      )}

      {turn.answer && <Answer text={turn.answer} />}

      {turn.status === "streaming" && !turn.answer && turn.toolCalls.length === 0 && (
        <div style={{ color: "var(--text-faint)" }}>working…</div>
      )}

      {turn.notice && <div className="turn__notice">{turn.notice}</div>}

      {turn.usage && (
        <div className="turn__usage mono">
          {turn.usage.input_tokens?.toLocaleString()} in ·{" "}
          {turn.usage.output_tokens?.toLocaleString()} out
          {turn.usage.cache_read_input_tokens
            ? ` · ${turn.usage.cache_read_input_tokens.toLocaleString()} cached`
            : ""}
        </div>
      )}
    </article>
  );
}
