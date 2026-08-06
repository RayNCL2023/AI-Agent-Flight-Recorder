/** Unit label, library navigation, mode badge, live status and run cost. */

import { fmtCost, fmtTokens } from "../lib/format";
import { useStore } from "../store/useStore";
import { ModeBadge } from "./ModeBadge";

export function TopBar() {
  const view = useStore((s) => s.view);
  const run = useStore((s) => s.run);
  const timelines = useStore((s) => s.timelines);
  const goHome = useStore((s) => s.goHome);
  const deleteRun = useStore((s) => s.deleteRun);
  const setError = useStore((s) => s.setError);

  // Total across unique stored events (each stored once regardless of lanes).
  const uniques = new Map<string, { cost: number; tok: number }>();
  for (const events of Object.values(timelines)) {
    for (const e of events) {
      uniques.set(e.id, { cost: e.cost_usd, tok: e.tokens_in + e.tokens_out });
    }
  }
  let cost = 0;
  let tokens = 0;
  for (const v of uniques.values()) {
    cost += v.cost;
    tokens += v.tok;
  }

  const exportRun = async () => {
    if (!run) return;
    try {
      const res = await fetch(`/api/runs/${run.id}/export`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `afr-trace-${run.id.slice(0, 8)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <header className="flex h-11 shrink-0 items-center gap-3 border-b border-line bg-panel px-3">
      {/* the black box is orange */}
      <button
        onClick={goHome}
        className="flex items-center gap-2 text-left"
        title="Back to the trace library"
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-sm bg-accent text-[13px] font-bold text-bg">
          ⏺
        </span>
        <div className="leading-none">
          <div className="text-[12px] font-semibold tracking-wide text-ink">
            AGENT FLIGHT RECORDER
          </div>
          <div className="stencil mt-0.5 !text-[8px]">immutable · branching · replayable</div>
        </div>
      </button>

      {view === "trace" && run && (
        <>
          <div className="mx-1 h-5 w-px bg-line" />
          <button
            onClick={goHome}
            className="rounded border border-line px-2 py-1 text-[11px] text-dim hover:border-accent hover:text-ink"
          >
            ⌂ Library
          </button>
          <span className="hidden max-w-56 truncate text-[11px] text-ink md:inline">
            {run.title}
          </span>
          {run.source === "recorded" && (
            <span className="stencil hidden !text-[8px] text-lane-1 lg:inline">
              ● recorded trace
            </span>
          )}
          <button
            onClick={exportRun}
            className="rounded border border-line px-2 py-1 text-[11px] text-dim hover:text-ink"
            title="Download this trace as a portable JSON bundle"
          >
            ⇩ Export
          </button>
          {run.source !== "recorded" && (
            <button
              onClick={() => {
                if (window.confirm(`Delete run “${run.title}” and all its branches?`))
                  void deleteRun(run.id);
              }}
              className="rounded border border-line px-2 py-1 text-[11px] text-dim hover:border-err hover:text-err"
              title="Delete this live run"
            >
              🗑
            </button>
          )}
        </>
      )}

      <div className="flex-1" />

      {view === "trace" && run && (
        <div className="hidden items-center gap-3 text-[11px] sm:flex">
          <span
            className={`flex items-center gap-1.5 ${
              run.status === "running" ? "text-accent" : "text-dim"
            }`}
          >
            {run.status === "running" && <span className="rec-pulse">●</span>}
            {run.status.toUpperCase()}
          </span>
          <span className="text-dim">
            {fmtTokens(tokens)} tok · <span className="text-ink">{fmtCost(cost)}</span>
          </span>
        </div>
      )}

      <ModeBadge />
    </header>
  );
}
