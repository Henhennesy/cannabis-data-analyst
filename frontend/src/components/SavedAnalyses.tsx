import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  deleteAnalysis,
  fetchAnalyses,
  rerunAnalysis,
  saveAnalysis,
} from "../lib/api";
import type { RerunResult, SavedAnalysisSummary, Turn } from "../lib/types";

/**
 * Saved analyses.
 *
 * A saved analysis is a re-runnable measurement, not a bookmark. Re-running
 * replays the original tool inputs -- the model is never asked again -- so the
 * month-over-month comparison cannot drift because it phrased a query
 * differently the second time.
 */
export function SavedAnalyses({ currentTurn }: { currentTurn: Turn | null }) {
  const qc = useQueryClient();
  const [rerun, setRerun] = useState<RerunResult | null>(null);

  const { data: saved = [] } = useQuery({
    queryKey: ["analyses"],
    queryFn: fetchAnalyses,
  });

  const doSave = useMutation({
    mutationFn: () => {
      const calls = (currentTurn?.toolCalls ?? [])
        .filter((c) => c.envelope && !c.envelope.error)
        .map((c) => ({
          tool_use_id: c.id,
          tool_name: c.name,
          tool_input: c.input,
          envelope: c.envelope!,
        }));
      return saveAnalysis(currentTurn!.question, calls);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["analyses"] }),
  });

  const doRerun = useMutation({
    mutationFn: rerunAnalysis,
    onSuccess: setRerun,
  });

  const doDelete = useMutation({
    mutationFn: deleteAnalysis,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["analyses"] }),
  });

  const savable =
    currentTurn?.status === "done" &&
    currentTurn.toolCalls.some((c) => c.envelope && !c.envelope.error);

  return (
    <div className="saved">
      <div className="saved__head">
        <span className="saved__title">Saved analyses</span>
        <button
          className="saved__save"
          disabled={!savable || doSave.isPending}
          onClick={() => doSave.mutate()}
          title={
            savable
              ? "Save this question and its queries so they can be re-run"
              : "Ask a question first — there is nothing to re-run yet"
          }
        >
          {doSave.isPending ? "saving…" : "+ save this"}
        </button>
      </div>

      {saved.length === 0 ? (
        <p className="saved__empty">
          Save an analysis to re-run it against next month's load and see what
          moved.
        </p>
      ) : (
        <ul className="saved__list">
          {saved.map((a) => (
            <SavedRow
              key={a.id}
              analysis={a}
              busy={doRerun.isPending}
              onRerun={() => doRerun.mutate(a.id)}
              onDelete={() => doDelete.mutate(a.id)}
            />
          ))}
        </ul>
      )}

      {rerun && <RerunReport result={rerun} onClose={() => setRerun(null)} />}
    </div>
  );
}

function SavedRow({
  analysis,
  busy,
  onRerun,
  onDelete,
}: {
  analysis: SavedAnalysisSummary;
  busy: boolean;
  onRerun: () => void;
  onDelete: () => void;
}) {
  return (
    <li className="saved__item">
      <div className="saved__item-name" title={analysis.question}>
        {analysis.name}
      </div>
      <div className="saved__item-meta mono">
        {analysis.created_at.slice(0, 10)} · {analysis.call_count} quer
        {analysis.call_count === 1 ? "y" : "ies"}
      </div>
      <div className="saved__item-actions">
        <button onClick={onRerun} disabled={busy}>
          {busy ? "…" : "re-run"}
        </button>
        <button onClick={onDelete} title="Delete">
          ×
        </button>
      </div>
    </li>
  );
}

function RerunReport({
  result,
  onClose,
}: {
  result: RerunResult;
  onClose: () => void;
}) {
  const totalChanged = result.results.reduce(
    (n, r) => n + (r.diff?.changed.length ?? 0),
    0,
  );
  const totalAdded = result.results.reduce(
    (n, r) => n + (r.diff?.added.length ?? 0),
    0,
  );
  const totalRemoved = result.results.reduce(
    (n, r) => n + (r.diff?.removed.length ?? 0),
    0,
  );

  return (
    <div className="rerun">
      <div className="rerun__head">
        <span>{result.analysis.name}</span>
        <button onClick={onClose} aria-label="Close">×</button>
      </div>

      <div className={result.data_changed ? "rerun__banner" : "rerun__banner rerun__banner--same"}>
        {result.data_changed
          ? "The data has been reloaded since this was saved."
          : "Same data version as when this was saved — nothing should have moved."}
        <div className="mono rerun__fingerprints">
          {result.saved_fingerprint} → {result.current_fingerprint}
        </div>
      </div>

      {totalChanged === 0 && totalAdded === 0 && totalRemoved === 0 ? (
        <p className="rerun__none">No values changed.</p>
      ) : (
        <div className="rerun__summary mono">
          {totalChanged} changed · {totalAdded} new · {totalRemoved} gone
        </div>
      )}

      {result.results.map((r) => (
        <div key={r.tool_use_id} className="rerun__call">
          <div className="rerun__call-name mono">{r.tool_name}</div>
          {!r.diff ? (
            <p className="rerun__none">not comparable</p>
          ) : (
            <>
              {r.diff.changed.slice(0, 20).map((c) => (
                <div key={c.key} className="rerun__change">
                  <div className="rerun__change-key">{c.key}</div>
                  {c.fields.map((f) => (
                    <div key={f.column} className="rerun__field mono">
                      <span className="rerun__field-col">{f.column}</span>
                      <span className="rerun__field-before">
                        {f.before.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      </span>
                      <span className="rerun__arrow">→</span>
                      <span className="rerun__field-after">
                        {f.after.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      </span>
                      {f.pct_change !== null && (
                        <span
                          className={
                            f.delta >= 0
                              ? "rerun__pct rerun__pct--up"
                              : "rerun__pct rerun__pct--down"
                          }
                        >
                          {f.delta >= 0 ? "+" : ""}
                          {f.pct_change.toFixed(1)}%
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              ))}
              {r.diff.added.map((a) => (
                <div key={a.key} className="rerun__added mono">
                  new · {a.key}
                </div>
              ))}
              {r.diff.removed.map((a) => (
                <div key={a.key} className="rerun__removed mono">
                  gone · {a.key}
                </div>
              ))}
            </>
          )}
        </div>
      ))}
    </div>
  );
}
