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

/** What the model emits instead of data points. */
export interface ChartSpec {
  type: "bar" | "line" | "stacked_bar" | "table";
  source_tool_call: string;
  x: string;
  y: string;
  series: string | null;
  title: string;
  caption: string;
}

/** A figure stated in prose that no tool result this turn supports. */
export interface UnverifiedFigure {
  text: string;
  value: number;
  start: number;
  end: number;
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
  | { type: "unverified_figures"; text: string; figures: UnverifiedFigure[] }
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
  charts: ChartSpec[];
  unverified: UnverifiedFigure[];
  status: "streaming" | "done" | "error" | "refused";
  notice?: string;
  usage?: Record<string, number>;
}

export interface SavedAnalysisSummary {
  id: string;
  name: string;
  question: string;
  created_at: string;
  fingerprint: string;
  call_count: number;
  tools: string[];
}

export interface DiffField {
  column: string;
  before: number;
  after: number;
  delta: number;
  pct_change: number | null;
}

export interface Diff {
  added: { key: string; row: Record<string, unknown> }[];
  removed: { key: string; row: Record<string, unknown> }[];
  changed: { key: string; fields: DiffField[] }[];
  unchanged_count: number;
}

export interface RerunResult {
  analysis: SavedAnalysisSummary;
  saved_fingerprint: string;
  current_fingerprint: string;
  data_changed: boolean;
  results: {
    tool_use_id: string;
    tool_name: string;
    tool_input: Record<string, unknown>;
    before: ToolEnvelope;
    after: ToolEnvelope;
    diff: Diff | null;
  }[];
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
