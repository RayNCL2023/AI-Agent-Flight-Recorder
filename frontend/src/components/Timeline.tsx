/**
 * The flight-data strip: one horizontal lane per branch, event nodes plotted
 * by sequence number, fork connectors drawn as curves from the exact event
 * where a branch diverged, and an orange playhead for scrubbing.
 */

import { useEffect, useMemo, useRef } from "react";
import type { BranchOut, EventOut } from "../api/types";
import {
  EVENT_GLYPH,
  EVENT_TINT,
  LABEL_TINT,
  fmtCost,
  fmtTokens,
  laneColor,
} from "../lib/format";
import { branchStats, sortedBranches, useStore } from "../store/useStore";

const LANE_H = 60;
const STEP = 52;
const PAD_X = 28;
const HEADER_W = 208;

function x(seq: number) {
  return PAD_X + (seq - 1) * STEP;
}

export function Timeline() {
  const run = useStore((s) => s.run);
  const timelines = useStore((s) => s.timelines);
  const selection = useStore((s) => s.selection);
  const freshEventIds = useStore((s) => s.freshEventIds);
  const followLive = useStore((s) => s.followLive);
  const select = useStore((s) => s.select);
  const scroller = useRef<HTMLDivElement>(null);

  const branches = useMemo(
    () => (run ? sortedBranches(run.branches) : []),
    [run],
  );

  const maxSeq = useMemo(
    () =>
      Math.max(
        1,
        ...Object.values(timelines).flatMap((events) =>
          events.map((e) => e.seq),
        ),
      ),
    [timelines],
  );

  useEffect(() => {
    if (followLive && scroller.current) {
      scroller.current.scrollTo({
        left: scroller.current.scrollWidth,
        behavior: "smooth",
      });
    }
  }, [maxSeq, followLive]);

  if (!run) return null;

  const contentW = x(maxSeq) + STEP + PAD_X;
  const contentH = branches.length * LANE_H;
  const laneY = (i: number) => i * LANE_H + LANE_H / 2;

  return (
    <div className="flex min-h-0 flex-1 flex-col border-b border-line bg-panel">
      <div className="flex items-center justify-between border-b border-line px-3 py-1.5">
        <span className="stencil">Timeline — flight data</span>
        <span className="stencil">
          {branches.length} branch{branches.length === 1 ? "" : "es"} ·{" "}
          {maxSeq} steps
        </span>
      </div>

      <div ref={scroller} className="relative min-h-0 flex-1 overflow-auto">
        <div
          className="relative"
          style={{ width: HEADER_W + contentW, height: contentH, minHeight: "100%" }}
        >
          {/* fork connectors */}
          <svg
            className="pointer-events-none absolute top-0"
            style={{ left: HEADER_W, width: contentW, height: contentH }}
            aria-hidden
          >
            {branches.map((branch, i) => {
              if (!branch.parent_branch_id || !branch.fork_seq) return null;
              const parentIdx = branches.findIndex(
                (b) => b.id === branch.parent_branch_id,
              );
              if (parentIdx === -1) return null;
              const x0 = x(Math.max(1, branch.fork_seq - 1));
              const x1 = x(branch.fork_seq);
              const y0 = laneY(parentIdx);
              const y1 = laneY(i);
              const mid = (x0 + x1) / 2;
              return (
                <path
                  key={branch.id}
                  d={`M ${x0} ${y0} C ${mid} ${y0}, ${mid} ${y1}, ${x1} ${y1}`}
                  fill="none"
                  stroke={laneColor(branch.color_index)}
                  strokeWidth={1.5}
                  strokeDasharray="4 3"
                  opacity={0.8}
                />
              );
            })}
          </svg>

          {/* playhead */}
          {selection.seq !== null && (
            <div
              className="pointer-events-none absolute top-0 z-10 w-px bg-accent transition-[left] duration-200"
              style={{ left: HEADER_W + x(selection.seq), height: contentH }}
            >
              <div className="absolute -left-[5px] -top-0 h-[11px] w-[11px] rotate-45 border border-accent bg-bg" />
            </div>
          )}

          {branches.map((branch, i) => (
            <Lane
              key={branch.id}
              branch={branch}
              index={i}
              events={timelines[branch.id] ?? []}
              selection={selection}
              freshEventIds={freshEventIds}
              onSelect={select}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function Lane({
  branch,
  index,
  events,
  selection,
  freshEventIds,
  onSelect,
}: {
  branch: BranchOut;
  index: number;
  events: EventOut[];
  selection: { branchId: string | null; seq: number | null };
  freshEventIds: Set<string>;
  onSelect: (branchId: string, seq: number) => void;
}) {
  const own = events.filter((e) => e.branch_id === branch.id);
  const stats = branchStats(events);
  const color = laneColor(branch.color_index);
  const isSelected = selection.branchId === branch.id;

  return (
    <div
      className={`absolute left-0 right-0 ${branch.parent_branch_id ? "lane-in" : ""}`}
      style={{ top: index * LANE_H, height: LANE_H }}
    >
      {/* guide line across own event range */}
      {own.length > 0 && (
        <div
          className="absolute"
          style={{
            left: HEADER_W + x(own[0].seq),
            width: x(own.at(-1)!.seq) - x(own[0].seq),
            top: LANE_H / 2,
            height: 1,
            background: color,
            opacity: 0.25,
          }}
        />
      )}

      {/* sticky lane header */}
      <div
        className={`sticky left-0 z-20 flex h-full flex-col justify-center gap-0.5 border-b border-r border-line px-3 ${
          isSelected ? "bg-panel-2" : "bg-panel"
        }`}
        style={{ width: HEADER_W, boxShadow: isSelected ? `inset 2px 0 0 ${color}` : undefined }}
      >
        <div className="flex items-center gap-2 overflow-hidden">
          <span
            className="h-2 w-2 shrink-0 rounded-full"
            style={{ background: color }}
          />
          <span className="truncate text-xs text-ink">{branch.name}</span>
          {(branch.status === "running" || branch.status === "pending") && (
            <span className="rec-pulse shrink-0 text-[9px] text-accent">●REC</span>
          )}
        </div>
        <div className="flex items-center gap-2 text-[10px] text-dim">
          <span style={{ color: LABEL_TINT[branch.label] }}>
            {branch.label === "unlabeled" ? branch.status : branch.label}
          </span>
          <span>{fmtTokens(stats.tokensIn + stats.tokensOut)} tok</span>
          <span>{fmtCost(stats.costUsd)}</span>
        </div>
      </div>

      {/* event nodes */}
      {own.map((ev) => {
        const active = isSelected && selection.seq === ev.seq;
        return (
          <button
            key={ev.id}
            onClick={() => onSelect(branch.id, ev.seq)}
            title={`#${ev.seq} ${ev.type} — ${ev.name}`}
            aria-label={`step ${ev.seq}: ${ev.name}`}
            className={`absolute z-10 flex h-7 w-7 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border bg-bg text-[11px] leading-none transition-transform hover:scale-110 ${
              freshEventIds.has(ev.id) ? "node-pop" : ""
            }`}
            style={{
              left: HEADER_W + x(ev.seq),
              top: LANE_H / 2,
              borderColor: active ? "var(--color-accent)" : EVENT_TINT[ev.type],
              color: EVENT_TINT[ev.type],
              boxShadow: active
                ? "0 0 0 3px var(--color-accent-soft)"
                : undefined,
            }}
          >
            {EVENT_GLYPH[ev.type]}
          </button>
        );
      })}
    </div>
  );
}
