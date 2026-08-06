/**
 * Divergence panel: the selected branch against its parent — aligned event
 * rows, the AI verdict + diagnosis, and a word-level diff of final answers.
 */

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { BranchDiff, EventOut } from "../api/types";
import { wordDiff } from "../lib/diff";
import {
  ANALYSIS_SOURCE_LABEL,
  EVENT_GLYPH,
  LABEL_TINT,
  fmtCost,
  fmtMs,
  fmtTokens,
  laneColor,
} from "../lib/format";
import { branchStats, useStore } from "../store/useStore";

export function DiffPanel() {
  const run = useStore((s) => s.run);
  const branch = useStore((s) =>
    s.run?.branches.find((b) => b.id === s.selection.branchId),
  );
  const timelines = useStore((s) => s.timelines);
  const [diff, setDiff] = useState<BranchDiff | null>(null);

  const branchSettled =
    branch && (branch.status === "completed" || branch.status === "failed");

  useEffect(() => {
    setDiff(null);
    if (!branch?.parent_branch_id || !branchSettled) return;
    let cancelled = false;
    api
      .diff(branch.id)
      .then((d) => !cancelled && setDiff(d))
      .catch(() => !cancelled && setDiff(null));
    return () => {
      cancelled = true;
    };
    // timelines in deps: refresh once streaming settles new events
  }, [branch?.id, branch?.status, branchSettled, timelines]);

  if (!run || !branch) {
    return <Shell><Empty>No branch selected.</Empty></Shell>;
  }

  const parent = run.branches.find((b) => b.id === branch.parent_branch_id);

  return (
    <Shell>
      <div className="flex flex-col gap-3 overflow-y-auto p-3">
        <div className="shrink-0 rounded border border-line bg-panel-2 p-2.5">
          <div className="stencil mb-1.5">Verdict</div>
          <div className="flex flex-wrap items-center gap-2">
            <span
              className="rounded-sm border px-1.5 py-0.5 text-[10px] uppercase tracking-wider"
              style={{
                color: LABEL_TINT[branch.label],
                borderColor: LABEL_TINT[branch.label],
              }}
            >
              {branch.label}
            </span>
            <span className="text-[10px] text-dim">{branch.name}</span>
            {branch.label !== "unlabeled" && (
              <span
                className="rounded-sm border border-line px-1.5 py-0.5 text-[8px] uppercase tracking-wider text-faint"
                title="Where this verdict comes from"
              >
                {ANALYSIS_SOURCE_LABEL[branch.analysis_source] ?? branch.analysis_source}
              </span>
            )}
          </div>
          {branch.diagnosis && (
            <p className="mt-2 whitespace-pre-wrap text-[11px] leading-relaxed text-ink">
              {branch.diagnosis}
            </p>
          )}
        </div>

        {run.summary && (
          <div className="shrink-0 rounded border border-line bg-panel-2 p-2.5">
            <div className="stencil mb-1.5">Run summary</div>
            <p className="text-[11px] leading-relaxed text-dim">{run.summary}</p>
          </div>
        )}

        {!parent && (
          <Empty>
            This is the root branch. Fork any step (F) and the divergence will
            appear here, side by side.
          </Empty>
        )}

        {parent && !branchSettled && <Empty>Waiting for the branch to settle…</Empty>}

        {parent && diff && (
          <>
            <StatDeltas
              parentEvents={timelines[parent.id] ?? []}
              branchEvents={timelines[branch.id] ?? []}
              parentName={parent.name}
              branchName={branch.name}
            />
            <div className="shrink-0 rounded border border-line bg-panel-2 p-2.5">
              <div className="stencil mb-1.5">
                Steps — {parent.name} vs {branch.name}
              </div>
              <div className="flex flex-col gap-px">
                {diff.entries.map((entry, i) => {
                  const ev = entry.b ?? entry.a;
                  if (!ev) return null;
                  const tint =
                    entry.kind === "same"
                      ? "var(--color-dim)"
                      : entry.kind === "changed"
                        ? "var(--color-warn)"
                        : entry.kind === "added_b"
                          ? "var(--color-ok)"
                          : "var(--color-err)";
                  const marker =
                    entry.kind === "same"
                      ? "="
                      : entry.kind === "changed"
                        ? "≠"
                        : entry.kind === "added_b"
                          ? "+"
                          : "−";
                  return (
                    <div
                      key={i}
                      className="flex items-center gap-2 rounded-sm px-1.5 py-0.5 text-[11px]"
                      style={{
                        background:
                          entry.kind === "same" ? "transparent" : "var(--color-bg)",
                      }}
                    >
                      <span className="w-3 text-center" style={{ color: tint }}>
                        {marker}
                      </span>
                      <span className="w-6 text-right text-dim">#{ev.seq}</span>
                      <span style={{ color: tint }}>{EVENT_GLYPH[ev.type]}</span>
                      <span className="truncate" style={{ color: tint }}>
                        {ev.name}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            <AnswerDiff diff={diff} parentColor={laneColor(parent.color_index)} branchColor={laneColor(branch.color_index)} />
          </>
        )}
      </div>
    </Shell>
  );
}

/** Token / latency / cost deltas between the fork and its parent. */
function StatDeltas({
  parentEvents,
  branchEvents,
  parentName,
  branchName,
}: {
  parentEvents: EventOut[];
  branchEvents: EventOut[];
  parentName: string;
  branchName: string;
}) {
  const a = branchStats(parentEvents);
  const b = branchStats(branchEvents);
  const rows: Array<[string, string, string, string]> = [
    [
      "tokens",
      fmtTokens(a.tokensIn + a.tokensOut),
      fmtTokens(b.tokensIn + b.tokensOut),
      signed(b.tokensIn + b.tokensOut - (a.tokensIn + a.tokensOut), fmtTokens),
    ],
    ["latency", fmtMs(a.durationMs), fmtMs(b.durationMs), signed(b.durationMs - a.durationMs, fmtMs)],
    ["cost", fmtCost(a.costUsd), fmtCost(b.costUsd), signed(b.costUsd - a.costUsd, fmtCost)],
    ["events", String(a.events), String(b.events), signed(b.events - a.events, String)],
  ];
  return (
    <div className="shrink-0 rounded border border-line bg-panel-2 p-2.5">
      <div className="stencil mb-1.5">Deltas — {branchName} vs {parentName}</div>
      <table className="w-full text-[11px]">
        <thead>
          <tr className="text-left text-[9px] uppercase tracking-wider text-faint">
            <th className="font-normal"></th>
            <th className="font-normal">{parentName}</th>
            <th className="font-normal">{branchName}</th>
            <th className="text-right font-normal">Δ</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, va, vb, delta]) => (
            <tr key={label}>
              <td className="py-0.5 text-dim">{label}</td>
              <td className="text-ink">{va}</td>
              <td className="text-ink">{vb}</td>
              <td
                className="text-right"
                style={{
                  color: delta.startsWith("+")
                    ? "var(--color-warn)"
                    : delta.startsWith("−")
                      ? "var(--color-ok)"
                      : "var(--color-dim)",
                }}
              >
                {delta}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function signed(delta: number, fmt: (n: number) => string): string {
  if (delta === 0) return "±0";
  return delta > 0 ? `+${fmt(delta)}` : `−${fmt(-delta)}`;
}

function AnswerDiff({
  diff,
  parentColor,
  branchColor,
}: {
  diff: BranchDiff;
  parentColor: string;
  branchColor: string;
}) {
  const answerA = findAnswer(diff, "a");
  const answerB = findAnswer(diff, "b");
  if (answerA === null || answerB === null) return null;
  const tokens = wordDiff(answerA, answerB);
  return (
    <div className="shrink-0 rounded border border-line bg-panel-2 p-2.5">
      <div className="stencil mb-1.5">Final answer — word diff</div>
      <p className="whitespace-pre-wrap text-[11px] leading-relaxed">
        {tokens.map((t, i) =>
          t.kind === "same" ? (
            <span key={i} className="text-dim">{t.text}</span>
          ) : t.kind === "removed" ? (
            <del key={i} className="rounded-sm px-0.5 no-underline" style={{ color: parentColor, background: "var(--color-bg)", textDecoration: "line-through" }}>
              {t.text}
            </del>
          ) : (
            <ins key={i} className="rounded-sm px-0.5 no-underline" style={{ color: branchColor, background: "var(--color-bg)" }}>
              {t.text}
            </ins>
          ),
        )}
      </p>
    </div>
  );
}

function findAnswer(diff: BranchDiff, side: "a" | "b"): string | null {
  for (let i = diff.entries.length - 1; i >= 0; i--) {
    const ev = diff.entries[i][side];
    if (ev?.type === "completion") return String(ev.payload.content ?? "");
  }
  return null;
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col border-l border-line bg-panel">
      <div className="flex h-8 shrink-0 items-center border-b border-line px-3">
        <h2 className="stencil">Divergence</h2>
      </div>
      {children}
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="p-4 text-[11px] leading-relaxed text-dim">{children}</p>;
}
