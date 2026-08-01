import type { CoverageBannerData, StreamEvent } from "./types";

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

/** Compact currency for prose; full precision belongs in the inspector. */
export function formatDollars(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}
