/**
 * Replay playback: advances the playhead along the selected branch using the
 * original inter-event timing (scaled by speed, clamped so long tool waits
 * don't stall the show and instant events remain legible).
 */

import { useEffect } from "react";
import { useStore } from "../store/useStore";

const MIN_GAP_MS = 150;
const MAX_GAP_MS = 2500;

export function usePlayback() {
  const playing = useStore((s) => s.playing);
  const speed = useStore((s) => s.speed);
  const selection = useStore((s) => s.selection);
  const timelines = useStore((s) => s.timelines);

  useEffect(() => {
    if (!playing || !selection.branchId) return;
    const events = timelines[selection.branchId] ?? [];
    const idx = events.findIndex((e) => e.seq === selection.seq);
    if (idx === -1 || idx >= events.length - 1) {
      useStore.setState({ playing: false });
      return;
    }
    const cur = events[idx];
    const next = events[idx + 1];
    const originalGap =
      new Date(next.ts).getTime() - new Date(cur.ts).getTime();
    const gap = Math.min(MAX_GAP_MS, Math.max(MIN_GAP_MS, originalGap / speed));
    const timer = setTimeout(() => {
      useStore.setState({
        selection: { branchId: selection.branchId, seq: next.seq },
      });
    }, gap);
    return () => clearTimeout(timer);
  }, [playing, speed, selection, timelines]);
}
