/** Typed mirror of the backend Pydantic schemas (backend/app/schemas.py). */

export type EventType =
  | "run_started"
  | "llm_message"
  | "reasoning"
  | "tool_call"
  | "tool_result"
  | "retry"
  | "error"
  | "completion"
  | "replay_miss";

export type RunStatus = "pending" | "running" | "completed" | "failed";
export type BranchStatus = RunStatus;
export type BranchLabel =
  | "success"
  | "hallucination"
  | "loop"
  | "failed"
  | "unrecorded"
  | "unlabeled";

/** Provenance of a branch verdict — never presented as anything else. */
export type AnalysisSource = "recorded" | "heuristic" | "llm";

/** Execution-mode facts served by /api/meta. */
export interface Meta {
  mode: "replay" | "live";
  live_available: boolean;
  model: string;
  version: string;
}

export interface EventOut {
  id: string;
  run_id: string;
  branch_id: string;
  seq: number;
  parent_event_id: string | null;
  trace_id: string;
  span_id: string;
  type: EventType;
  name: string;
  ts: string;
  duration_ms: number;
  payload: Record<string, unknown>;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  meta: Record<string, unknown>;
}

export interface BranchOut {
  id: string;
  run_id: string;
  name: string;
  parent_branch_id: string | null;
  fork_seq: number | null;
  overrides: {
    edited_prompt?: string | null;
    tool_overrides?: Record<string, Record<string, unknown>>;
  };
  status: BranchStatus;
  label: BranchLabel;
  diagnosis: string | null;
  analysis_source: AnalysisSource;
  color_index: number;
  created_at: string;
}

export interface BranchStats {
  branch_id: string;
  events: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  duration_ms: number;
}

export interface BranchTimeline {
  branch: BranchOut;
  events: EventOut[];
  stats: BranchStats;
}

/** A curated fork variant recorded alongside a library trace. */
export interface ExperimentOut {
  id: string;
  title: string;
  description: string;
  fork_seq: number;
  edited_prompt: string | null;
  tool_overrides: Record<string, Record<string, unknown>>;
  recorded_label: BranchLabel;
  recorded_diagnosis: string | null;
}

export interface RunOut {
  id: string;
  title: string;
  prompt: string;
  model: string;
  seed: number;
  status: RunStatus;
  summary: string | null;
  source: "recorded" | "live";
  description: string | null;
  tools_used: string[];
  experiments: ExperimentOut[];
  created_at: string;
}

export interface RunStatsOut {
  events: number;
  tokens: number;
  cost_usd: number;
  duration_ms: number;
}

/** Library card: a run plus aggregate stats over its stored events. */
export interface RunListItem extends RunOut {
  stats: RunStatsOut;
}

export interface RunDetail extends RunOut {
  branches: BranchOut[];
}

export interface ForkRequest {
  fork_seq: number;
  name?: string;
  edited_prompt?: string | null;
  tool_overrides?: Record<string, Record<string, unknown>>;
}

export interface DiffEntry {
  kind: "same" | "changed" | "added_a" | "added_b";
  a: EventOut | null;
  b: EventOut | null;
}

export interface BranchDiff {
  branch_a: string;
  branch_b: string;
  fork_seq: number | null;
  entries: DiffEntry[];
}

/** SSE frames published by the backend bus. */
export type StreamMessage =
  | { kind: "event"; event: EventOut }
  | { kind: "branch_update"; branch: BranchOut }
  | { kind: "run_update"; run: RunOut };
