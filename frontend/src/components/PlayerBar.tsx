/**
 * Black-box playback controls: play/pause, jump, speed, and a scrub slider
 * over the selected branch's timeline. Space toggles playback.
 */

import { useStore } from "../store/useStore";

export function PlayerBar() {
  const playing = useStore((s) => s.playing);
  const speed = useStore((s) => s.speed);
  const setPlaying = useStore((s) => s.setPlaying);
  const cycleSpeed = useStore((s) => s.cycleSpeed);
  const select = useStore((s) => s.select);
  const selection = useStore((s) => s.selection);
  const events = useStore((s) =>
    s.selection.branchId ? (s.timelines[s.selection.branchId] ?? []) : [],
  );

  const idx = events.findIndex((e) => e.seq === selection.seq);
  const atEnd = idx >= events.length - 1;
  const branchId = selection.branchId;

  const jump = (i: number) => {
    if (!branchId || events.length === 0) return;
    const clamped = Math.max(0, Math.min(events.length - 1, i));
    select(branchId, events[clamped].seq);
  };

  const toggle = () => {
    if (!branchId || events.length === 0) return;
    if (!playing && atEnd) jump(0); // replay from the top
    setPlaying(!playing);
  };

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() => jump(0)}
        disabled={!branchId}
        aria-label="Jump to first event"
        className="rounded border border-line px-1.5 py-0.5 text-[11px] text-dim hover:text-ink disabled:opacity-40"
      >
        ⏮
      </button>
      <button
        onClick={toggle}
        disabled={!branchId}
        aria-label={playing ? "Pause replay" : "Play replay"}
        title={playing ? "Pause (Space)" : "Play (Space)"}
        className="rounded border border-accent bg-accent-soft px-2.5 py-0.5 text-[11px] text-accent hover:bg-accent hover:text-bg disabled:opacity-40"
      >
        {playing ? "❚❚" : "▶"}
      </button>
      <button
        onClick={() => jump(events.length - 1)}
        disabled={!branchId}
        aria-label="Jump to last event"
        className="rounded border border-line px-1.5 py-0.5 text-[11px] text-dim hover:text-ink disabled:opacity-40"
      >
        ⏭
      </button>
      <button
        onClick={cycleSpeed}
        aria-label={`Playback speed ${speed}x`}
        className="w-8 rounded border border-line px-1 py-0.5 text-[10px] text-dim hover:text-ink"
      >
        {speed}×
      </button>
      <input
        type="range"
        min={0}
        max={Math.max(0, events.length - 1)}
        value={idx === -1 ? 0 : idx}
        onChange={(e) => jump(Number(e.target.value))}
        aria-label="Scrub timeline"
        className="player-scrub w-36"
        disabled={events.length === 0}
      />
      <span className="w-16 text-right text-[10px] tabular-nums text-dim">
        {idx === -1 ? "—" : `${idx + 1} / ${events.length}`}
      </span>
    </div>
  );
}
