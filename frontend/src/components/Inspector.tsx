import { useState } from "react";
import { downloadCsv } from "../lib/exports";
import type { ToolCall } from "../lib/types";

/**
 * The inspector: what produced this number.
 *
 * Written as a lab notebook rather than a debug console. A debug console is a
 * dump — everything, flat, in one colour, for a machine's benefit. A notebook
 * is a record kept by someone who expected to be asked "how do you know that?"
 * a month later: numbered entries, a ruled margin, observations in the hand of
 * the person who ran the experiment, and the raw readings underneath.
 *
 * That framing is not decoration. This pane is the last thing between a figure
 * and a client deck, and it should read like evidence.
 */
export function Inspector({
  calls,
  selectedId,
  onSelect,
  collapsed,
  onToggle,
}: {
  calls: ToolCall[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  collapsed: boolean;
  onToggle: () => void;
}) {
  if (collapsed) {
    return (
      <aside className="inspector inspector--collapsed">
        <button
          className="inspector__tab"
          onClick={onToggle}
          title="Show inspector"
          aria-label="Show inspector"
        >
          <span className="inspector__tab-text">INSPECTOR</span>
        </button>
      </aside>
    );
  }

  const selected = calls.find((c) => c.id === selectedId) ?? calls[calls.length - 1];

  return (
    <aside className="inspector">
      <div className="inspector__head">
        <span className="inspector__head-title">Inspector</span>
        <button className="inspector__collapse" onClick={onToggle} aria-label="Hide inspector">
          ×
        </button>
      </div>

      {calls.length === 0 ? (
        <div className="inspector__empty">
          Nothing recorded yet. Ask a question and every query it runs is
          entered here.
        </div>
      ) : (
        <>
          <ol className="inspector__index">
            {calls.map((c, i) => (
              <li key={c.id}>
                <button
                  className={
                    c.id === selected?.id
                      ? "inspector__entry inspector__entry--current"
                      : "inspector__entry"
                  }
                  onClick={() => onSelect(c.id)}
                >
                  <span className="inspector__entry-no">{i + 1}</span>
                  <span className="inspector__entry-name">{c.name}</span>
                  <span className="inspector__entry-rows">
                    {c.envelope?.error
                      ? "failed"
                      : c.envelope
                        ? `${c.envelope.row_count.toLocaleString()}`
                        : "…"}
                  </span>
                </button>
              </li>
            ))}
          </ol>

          {selected && <Entry call={selected} />}
        </>
      )}
    </aside>
  );
}

function Entry({ call }: { call: ToolCall }) {
  const env = call.envelope;
  const [showRows, setShowRows] = useState(false);

  if (!env) {
    return <div className="inspector__empty">Running…</div>;
  }

  return (
    <div className="notebook">
      {env.error && (
        <section className="notebook__section">
          <h3 className="notebook__label">Result</h3>
          <p className="notebook__error">{env.error}</p>
        </section>
      )}

      <section className="notebook__section">
        <h3 className="notebook__label">Method</h3>
        <dl className="notebook__facts">
          <dt>tool</dt>
          <dd>{call.name}</dd>
          <dt>relation</dt>
          <dd>{env.relation ?? "—"}</dd>
          <dt>rows</dt>
          <dd>
            {env.row_count.toLocaleString()}
            {env.truncated && <span className="notebook__flag"> truncated</span>}
          </dd>
        </dl>
      </section>

      <section className="notebook__section">
        <h3 className="notebook__label">Parameters</h3>
        <pre className="notebook__params">
          {JSON.stringify(call.input, null, 2)}
        </pre>
      </section>

      {env.sql && (
        <section className="notebook__section">
          <h3 className="notebook__label">Query as executed</h3>
          <pre className="notebook__sql">{env.sql}</pre>
        </section>
      )}

      <section className="notebook__section">
        <h3 className="notebook__label">Coverage</h3>
        <p className="notebook__coverage">
          {env.coverage.period_start === null
            ? "not derived for this query — state it from the query itself"
            : env.coverage.period_start === env.coverage.period_end
              ? `${env.coverage.period_start}`
              : `${env.coverage.period_start}–${env.coverage.period_end}`}
          {env.coverage.states.length > 0 && (
            <> · {env.coverage.states.length} state
              {env.coverage.states.length === 1 ? "" : "s"}</>
          )}
        </p>
        {env.coverage.partial_periods.length > 0 && (
          <p className="notebook__caveat">
            {env.coverage.partial_periods.join(", ")} partial
          </p>
        )}
        {env.coverage.caveats.map((c, i) => (
          <p key={i} className="notebook__caveat">{c}</p>
        ))}
      </section>

      {env.notes.length > 0 && (
        <section className="notebook__section">
          <h3 className="notebook__label">Marginalia</h3>
          {env.notes.map((n, i) => (
            <p
              key={i}
              className={
                n.startsWith("DO NOT TOTAL") || n.startsWith("TRUNCATED")
                  ? "notebook__note notebook__note--loud"
                  : "notebook__note"
              }
            >
              {n}
            </p>
          ))}
        </section>
      )}

      {env.rows.length > 0 && (
        <section className="notebook__section">
          <div className="notebook__row-head">
            <h3 className="notebook__label">Readings</h3>
            <div className="notebook__row-actions">
              <button onClick={() => setShowRows((s) => !s)}>
                {showRows ? "hide" : "show"}
              </button>
              <button
                onClick={() =>
                  downloadCsv(env.rows, `${call.name}-${call.id.slice(-6)}.csv`)
                }
                title="Download all rows as CSV"
              >
                csv
              </button>
            </div>
          </div>
          {showRows && <RawRows rows={env.rows} />}
        </section>
      )}
    </div>
  );
}

function RawRows({ rows }: { rows: Record<string, unknown>[] }) {
  const columns = Object.keys(rows[0] ?? {});
  const shown = rows.slice(0, 40);
  return (
    <div className="notebook__rows-wrap">
      <table className="notebook__rows">
        <thead>
          <tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {shown.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => {
                const v = r[c];
                const numeric = typeof v === "number";
                return (
                  <td key={c} className={numeric ? "is-number" : undefined}>
                    {v === null || v === undefined
                      ? "—"
                      : numeric
                        ? (v as number).toLocaleString(undefined, {
                            maximumFractionDigits: 2,
                          })
                        : String(v)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > shown.length && (
        <p className="notebook__note">
          {shown.length} of {rows.length.toLocaleString()} shown — csv has all
        </p>
      )}
    </div>
  );
}
