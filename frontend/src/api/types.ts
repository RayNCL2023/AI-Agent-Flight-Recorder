/** Typed mirror of the backend Pydantic schemas (backend/app/schemas.py). */

export type EventType =
  | "run_started"
  | "llm_message"
  | "reasoning"
  | "tool_call"
  | "tool_result"
  | "retry"
  | "error"
  | "completion";

export type RunStatus = "pending" | "running" | "completed" | "failed";
export type BranchStatus = RunStatus;
export type BranchLabel =
  | "success"
  | "hallucination"
  | "loop"
  | "failed"
  | "unlabeled";

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

export interface RunOut {
  id: string;
  title: string;
  prompt: string;
  model: string;
  seed: number;
  status: RunStatus;
  summary: string | null;
  created_at: string;
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
