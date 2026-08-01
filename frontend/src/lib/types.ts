/** Mirrors backend/app/envelope.py and the SSE event shapes in main.py. */

export interface Coverage {
  period_start: number | null;
  period_end: number | null;
  states: string[];
  partial_periods: number[];
  caveats: string[];
}

export interface ToolEnvelope {
  rows: Record<string, unknown>[];
  row_count: number;
  sql: string;
  params: Record<string, unknown>;
  coverage: Coverage;
  truncated: boolean;
  relation: string | null;
  error: string | null;
  notes: string[];
}

export type StreamEvent =
  | { type: "start"; conversation_id: string }
  | { type: "thinking"; text: string }
  | { type: "text"; text: string }
  | { type: "tool_call"; tool_name: string; tool_use_id: string; tool_input: Record<string, unknown> }
  | { type: "tool_result"; tool_name: string; tool_use_id: string; envelope: ToolEnvelope }
  | { type: "turn_end"; stop_reason?: string; usage?: Record<string, number> }
  | { type: "refusal"; text: string }
  | { type: "error"; text: string }
  | { type: "done" };

/** One tool invocation, paired with its result once it arrives. */
export interface ToolCall {
  id: string;
  name: string;
  input: Record<string, unknown>;
  envelope?: ToolEnvelope;
}

export interface Turn {
  question: string;
  thinking: string;
  answer: string;
  toolCalls: ToolCall[];
  status: "streaming" | "done" | "error" | "refused";
  notice?: string;
  usage?: Record<string, number>;
}

export interface CoverageBannerData {
  period_start: number;
  period_end: number;
  states: string[];
  state_count: number;
  partial_periods: number[];
  caveats: string[];
  notes: string[];
}
