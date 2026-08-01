import { useState } from "react";
import type { ToolCall } from "../lib/types";

/**
 * One tool call, collapsed by default and expandable to the SQL, params, notes
 * and rows behind it.
 *
 * This is the audit surface. Every number in an answer traces back to one of
 * these, and the whole point of the project is that you can check a figure here
 * before it goes into a deck. The full inspector pane is Milestone 8; this is
 * the same information inline.
 */
export function ToolCallRow({ call, index }: { call: ToolCall; index: number }) {
  const [open, setOpen] = useState(false);
  const env = call.envelope;

  const summary = !env
    ? "running…"
    : env.error
      ? "failed"
      : `${env.row_count.toLocaleString()} row${env.row_count === 1 ? "" : "s"}`;

  const args = Object.entries(call.input)
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(", ");

  return (
    <div className="tool">
      <button
        className="tool__head"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="tool__index">{open ? "−" : "+"}</span>
        <span className="tool__index">{index}</span>
        <span className="tool__name">{call.name}</span>
        <span className="mono" style={{ color: "var(--text-faint)" }}>
          ({args.length > 64 ? args.slice(0, 64) + "…" : args})
        </span>
        <span
          className={
            env?.error ? "tool__summary tool__summary--error" : "tool__summary"
          }
        >
          {summary}
        </span>
      </button>

      {open && env && (
        <div className="tool__body">
          {env.error && (
            <div className="tool__field">
              <span className="tool__field-label">Error</span>
              <div style={{ color: "var(--error)" }}>{env.error}</div>
            </div>
          )}

          {env.sql && (
            <div className="tool__field">
              <span className="tool__field-label">SQL executed</span>
              <pre className="tool__sql">{env.sql}</pre>
            </div>
          )}

          <div className="tool__field">
            <span className="tool__field-label">Coverage</span>
            <span className="mono">
              {env.coverage.period_start === env.coverage.period_end
                ? env.coverage.period_start ?? "—"
                : `${env.coverage.period_start}–${env.coverage.period_end}`}
              {" · "}
              {env.coverage.states.length} state
              {env.coverage.states.length === 1 ? "" : "s"}
              {env.relation ? ` · ${env.relation}` : ""}
            </span>
          </div>

          {env.notes.length > 0 && (
            <div className="tool__field">
              <span className="tool__field-label">Notes</span>
              {env.notes.map((n, i) => (
                <div
                  key={i}
                  className={
                    n.startsWith("DO NOT TOTAL") || n.includes("PARTIAL")
                      ? "tool__note tool__note--loud"
                      : "tool__note"
                  }
                >
                  · {n}
                </div>
              ))}
            </div>
          )}

          {env.rows.length > 0 && <RowTable rows={env.rows} total={env.row_count} />}
        </div>
      )}
    </div>
  );
}

/**
 * A year is a label, not a quantity. `2,025` reads as a number of things and
 * is actively misleading in a column headed `period_year`, so year-ish columns
 * are rendered verbatim.
 */
const YEAR_COLUMN = /(^|_)(year|period)$/i;

function formatCell(column: string, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value !== "number") return String(value);
  if (YEAR_COLUMN.test(column)) return String(value);
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function RowTable({
  rows,
  total,
}: {
  rows: Record<string, unknown>[];
  total: number;
}) {
  const columns = Object.keys(rows[0] ?? {});
  const shown = rows.slice(0, 12);

  return (
    <div className="tool__field">
      <span className="tool__field-label">Rows</span>
      <div style={{ overflowX: "auto" }}>
        <table className="tool__rows">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, i) => (
              <tr key={i}>
                {columns.map((c) => {
                  const v = row[c];
                  // Right-align true quantities; years stay left with labels.
                  const isQuantity = typeof v === "number" && !YEAR_COLUMN.test(c);
                  return (
                    <td key={c} className={isQuantity ? "is-number" : undefined}>
                      {formatCell(c, v)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {total > shown.length && (
        <div className="tool__more">
          showing {shown.length} of {total.toLocaleString()} rows
        </div>
      )}
    </div>
  );
}
