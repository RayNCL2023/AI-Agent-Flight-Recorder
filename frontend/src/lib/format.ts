/** Formatting helpers shared across panels. */

import type { EventType } from "../api/types";

export function fmtCost(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.001) return `$${(usd * 1000).toFixed(3)}‰`.replace("‰", "m");
  return `$${usd.toFixed(4)}`;
}

export function fmtTokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

export function fmtMs(ms: number): string {
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour12: false });
}

export const EVENT_GLYPH: Record<EventType, string> = {
  run_started: "▶",
  llm_message: "◆",
  reasoning: "…",
  tool_call: "⚙",
  tool_result: "⛁",
  retry: "↻",
  error: "✕",
  completion: "■",
};

export const EVENT_TINT: Record<EventType, string> = {
  run_started: "var(--color-dim)",
  llm_message: "var(--color-lane-5)",
  reasoning: "var(--color-faint)",
  tool_call: "var(--color-lane-0)",
  tool_result: "var(--color-lane-1)",
  retry: "var(--color-warn)",
  error: "var(--color-err)",
  completion: "var(--color-ok)",
};

export function laneColor(index: number): string {
  return `var(--color-lane-${((index % 6) + 6) % 6})`;
}

export const LABEL_TINT: Record<string, string> = {
  success: "var(--color-ok)",
  hallucination: "var(--color-lane-2)",
  loop: "var(--color-warn)",
  failed: "var(--color-err)",
  unlabeled: "var(--color-faint)",
};
