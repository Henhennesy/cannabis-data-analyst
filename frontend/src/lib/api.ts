import type {
  CoverageBannerData,
  RerunResult,
  SavedAnalysisSummary,
  StreamEvent,
  ToolEnvelope,
} from "./types";

/** Vite proxies /api to the backend in dev; Caddy fronts both in deployment. */
const BASE = "/api";

export async function fetchCoverage(): Promise<CoverageBannerData> {
  const r = await fetch(`${BASE}/coverage`);
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(`coverage unavailable (${r.status}) ${detail}`);
  }
  return r.json();
}

/**
 * Stream one turn.
 *
 * POST rather than EventSource because the question goes in the body and
 * EventSource cannot POST. That means parsing the SSE framing by hand: split
 * on the blank-line record separator and keep any partial record in the
 * buffer, because a chunk boundary can land mid-record.
 */
export async function streamChat(
  message: string,
  conversationId: string | null,
  onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId }),
    signal,
  });

  if (!response.ok || !response.body) {
    let detail = "";
    try {
      detail = (await response.json())?.detail ?? "";
    } catch {
      /* body may not be JSON */
    }
    throw new Error(detail || `chat failed (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Records are separated by a blank line. The final element is whatever is
    // left over -- possibly an incomplete record -- so it stays in the buffer.
    const records = buffer.split("\n\n");
    buffer = records.pop() ?? "";

    for (const record of records) {
      const line = record.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(6)) as StreamEvent);
      } catch {
        // A malformed record must not kill the stream; the turn still ends
        // with `done` and the user still gets whatever else arrives.
        console.warn("unparseable SSE record", record);
      }
    }
  }
}

// --- saved analyses --------------------------------------------------------

export async function fetchAnalyses(): Promise<SavedAnalysisSummary[]> {
  const r = await fetch(`${BASE}/analyses`);
  if (!r.ok) throw new Error(`could not list analyses (${r.status})`);
  return r.json();
}

export async function saveAnalysis(
  question: string,
  calls: {
    tool_use_id: string;
    tool_name: string;
    tool_input: Record<string, unknown>;
    envelope: ToolEnvelope;
  }[],
): Promise<SavedAnalysisSummary> {
  const r = await fetch(`${BASE}/analyses`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: "", question, calls }),
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw new Error(detail?.detail ?? `could not save (${r.status})`);
  }
  return r.json();
}

export async function rerunAnalysis(id: string): Promise<RerunResult> {
  const r = await fetch(`${BASE}/analyses/${id}/rerun`, { method: "POST" });
  if (!r.ok) throw new Error(`could not re-run (${r.status})`);
  return r.json();
}

export async function deleteAnalysis(id: string): Promise<void> {
  const r = await fetch(`${BASE}/analyses/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`could not delete (${r.status})`);
}

/** Compact currency for prose; full precision belongs in the inspector. */
export function formatDollars(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}
