/** Unit label, run selector, live status and total run cost. */

import { fmtCost, fmtTokens } from "../lib/format";
import { useStore } from "../store/useStore";

export function TopBar() {
  const runs = useStore((s) => s.runs);
  const run = useStore((s) => s.run);
  const timelines = useStore((s) => s.timelines);
  const openRun = useStore((s) => s.openRun);
  const deleteRun = useStore((s) => s.deleteRun);
  const setLauncherOpen = useStore((s) => s.setLauncherOpen);
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
      <div className="flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-sm bg-accent text-[13px] font-bold text-bg">
          ⏺
        </span>
        <div className="leading-none">
          <div className="text-[12px] font-semibold tracking-wide text-ink">
            AGENT FLIGHT RECORDER
          </div>
          <div className="stencil mt-0.5 !text-[8px]">immutable · branching · replayable</div>
        </div>
      </div>

      <div className="mx-2 h-5 w-px bg-line" />

      <select
        value={run?.id ?? ""}
        onChange={(e) => e.target.value && openRun(e.target.value)}
        className="max-w-64 rounded border border-line bg-bg px-2 py-1 text-[11px] text-ink"
        aria-label="Select run"
      >
        {runs.length === 0 && <option value="">no runs recorded</option>}
        {runs.map((r) => (
          <option key={r.id} value={r.id}>
            {r.title}
          </option>
        ))}
      </select>

      <button
        onClick={() => setLauncherOpen(true)}
        className="rounded border border-accent bg-accent-soft px-2.5 py-1 text-[11px] text-accent transition-colors hover:bg-accent hover:text-bg"
      >
        ▶ New run <span className="opacity-60">(N)</span>
      </button>

      {run && (
        <>
          <button
            onClick={exportRun}
            className="rounded border border-line px-2 py-1 text-[11px] text-dim hover:text-ink"
            title="Download trace JSON"
          >
            ⇩ Export
          </button>
          <button
            onClick={() => {
              if (window.confirm(`Delete run “${run.title}” and all its branches?`))
                void deleteRun(run.id);
            }}
            className="rounded border border-line px-2 py-1 text-[11px] text-dim hover:border-err hover:text-err"
            title="Delete run"
          >
            🗑
          </button>
        </>
      )}

      <div className="flex-1" />

      {run && (
        <div className="flex items-center gap-3 text-[11px]">
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
          <span className="hidden text-faint sm:inline">{run.model} · seed {run.seed}</span>
        </div>
      )}
    </header>
  );
}
