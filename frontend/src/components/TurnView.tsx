import type { Turn } from "../lib/types";
import { Answer } from "./Answer";
import { ChartCanvas } from "./ChartCanvas";
import { ToolCallRow } from "./ToolCallRow";

export function TurnView({ turn }: { turn: Turn }) {
  // Charts render against the rows of the tool call they name.
  const envelopes = new Map(
    turn.toolCalls.filter((c) => c.envelope).map((c) => [c.id, c.envelope!]),
  );

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

      {turn.charts.map((spec, i) => (
        <ChartCanvas
          key={`${spec.source_tool_call}-${i}`}
          spec={spec}
          source={envelopes.get(spec.source_tool_call)}
        />
      ))}

      {turn.answer && <Answer text={turn.answer} />}

      {turn.status === "streaming" && !turn.answer && turn.toolCalls.length === 0 && (
        <div style={{ color: "var(--text-faint)" }}>working…</div>
      )}

      {turn.unverified.length > 0 && <UnverifiedFigures turn={turn} />}

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

/**
 * Figures stated in prose that appear in no tool result from this turn.
 *
 * Deliberately loud. Everything else in this interface is quiet, because the
 * numbers are trustworthy by construction; this is the one case where they may
 * not be, and it is the last thing standing between a fabricated figure and a
 * client deck. Advisory, not blocking -- the answer is still shown, because a
 * flagged figure is usually a rounding artefact and occasionally a real
 * problem, and only a human can tell which.
 */
function UnverifiedFigures({ turn }: { turn: Turn }) {
  return (
    <div className="unverified" role="alert">
      <div className="unverified__head">
        {turn.unverified.length} figure{turn.unverified.length === 1 ? "" : "s"} not
        traced to a tool result
      </div>
      <ul className="unverified__list">
        {turn.unverified.map((f, i) => (
          <li key={i}>
            <code className="unverified__value">{f.text}</code>
          </li>
        ))}
      </ul>
      <div className="unverified__hint">
        Every other number above appears in one of the tool results. These do
        not — check them against the SQL before using them.
      </div>
    </div>
  );
}
