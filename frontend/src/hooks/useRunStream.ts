/** SSE subscription for the active run, with automatic resync on reconnect. */

import { useEffect } from "react";
import type { StreamMessage } from "../api/types";
import { useStore } from "../store/useStore";

export function useRunStream(runId: string | null) {
  const handleStream = useStore((s) => s.handleStream);
  const openRun = useStore((s) => s.openRun);

  useEffect(() => {
    if (!runId) return;
    const source = new EventSource(`/api/stream/runs/${runId}`);
    let hadError = false;

    const onMessage = (e: MessageEvent) => {
      if (hadError) {
        // Connection recovered: REST snapshot fills any gap we missed.
        hadError = false;
        void openRun(runId);
      }
      handleStream(JSON.parse(e.data) as StreamMessage);
    };
    source.addEventListener("event", onMessage);
    source.addEventListener("branch_update", onMessage);
    source.addEventListener("run_update", onMessage);
    source.onerror = () => {
      hadError = true; // EventSource retries on its own
    };
    return () => source.close();
  }, [runId, handleStream, openRun]);
}
