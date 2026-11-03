// Types mirroring the FastAPI hub's JSON responses.

export interface TimingSummary {
  n: number;
  median: number | null;
  p95: number | null;
  max: number | null;
}

export interface TurnTimings {
  asr_s: number | null;
  classifier_s: number | null;
  tool_s: number | null;
  tts_first_s: number | null;
  e2e_s: number | null;
}

export interface Turn {
  turn: number;
  group: string | null;
  raw_choice: string | null;
  router_model: string | null;
  top_prob: number | null;
  gap: number | null;
  gate: string;
  dispatch: string;
  tool: string | null;
  glm_reason: string | null;
  escalate: boolean;
  outcome: string;
  timings: TurnTimings;
}

export interface RunConfig {
  orchestration_mode: string | null;
  router_model: string | null;
  tts_backend: string | null;
  tts_model: string | null;
  asr_backend: string | null;
  asr_model: string | null;
  classifier_timeout_s: number | null;
  cloud_escalation: boolean | null;
}

export interface RunSummary {
  run_id: string;
  started_at: number | null;
  ended_at: number | null;
  schema: string;
  turns: number;
  median_e2e_s: number | null;
  p95_e2e_s: number | null;
  classifier_ok: number;
  classifier_fail: number;
  config: RunConfig;
}

export interface Histogram {
  bins: { lo: number; hi: number; count: number }[];
  overflow: number;
}

export interface ClassifierHealth {
  accepted: number;
  escalated: number;
  rejected: number;
  timeout: number;
  error: number;
  bypass: number;
  multiple_actions: number;
  latency: TimingSummary;
  histogram: Histogram;
}

export interface ToolActivity {
  tool: string;
  group: string | null;
  count: number;
  median_s: number | null;
}

export interface ToolSpan {
  tool: string;
  group: string | null;
  at: number | null;
  duration_s: number | null;
}

export interface RunDetail {
  run_id: string;
  started_at: number | null;
  ended_at: number | null;
  schema: string;
  config: RunConfig;
  turns: Turn[];
  aggregates: {
    e2e_s: TimingSummary;
    asr_s: TimingSummary;
    classifier_s: TimingSummary;
    tool_s: TimingSummary;
    tts_first_s: TimingSummary;
  };
  group_distribution: Record<string, number>;
  classifier_health: ClassifierHealth;
  tool_activity: ToolActivity[];
  tool_timeline: ToolSpan[];
  dispatch_breakdown: Record<string, number>;
}

export interface GroupDisplay {
  name: string;
  color: string;
  description?: string;
  escalate?: boolean;
}

export interface OutcomeDisplay {
  name: string;
  color: string;
}

export interface DispatchDisplay {
  name: string;
  color: string;
}

export interface DisplayNames {
  groups: Record<string, GroupDisplay>;
  outcomes: Record<string, OutcomeDisplay>;
  dispatch: Record<string, DispatchDisplay>;
  tools: Record<string, string>;
}

export interface State {
  data_dir: string;
  runs: RunSummary[];
  groups: string[];
  display_names: DisplayNames;
}
