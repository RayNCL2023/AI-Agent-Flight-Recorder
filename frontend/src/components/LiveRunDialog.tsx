/**
 * Live-run dialog. Renders only when Live Mode is actually available — free
 * text input never appears in Replay Mode, because nothing could honestly
 * answer it there.
 */

import { useState } from "react";
import { useStore } from "../store/useStore";

const EXAMPLES = [
  "What is 2+2*3? Also what's the weather in Paris?",
  "How tall is the Eiffel Tower? And compute 330*3.28",
  "Read notes.txt and tell me what the team should investigate.",
  "Compare Python and Rust for a high-throughput API server.",
];

export function LiveRunDialog() {
  const open = useStore((s) => s.launcherOpen);
  const liveAvailable = useStore((s) => Boolean(s.meta?.live_available));
  const model = useStore((s) => s.meta?.model ?? "");
  const setOpen = useStore((s) => s.setLauncherOpen);
  const createRun = useStore((s) => s.createRun);
  const setError = useStore((s) => s.setError);
  const [prompt, setPrompt] = useState(EXAMPLES[0]);
  const [seed, setSeed] = useState(42);
  const [busy, setBusy] = useState(false);

  if (!open || !liveAvailable) return null;

  const launch = async () => {
    if (!prompt.trim()) return;
    setBusy(true);
    try {
      await createRun(prompt.trim(), seed);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-bg/80 p-4"
      onClick={() => setOpen(false)}
      role="dialog"
      aria-modal="true"
      aria-label="Record a live run"
    >
      <div
        className="w-full max-w-xl rounded border border-line bg-panel shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-2">
          <h2 className="stencil">▶ Record a live run</h2>
          <button onClick={() => setOpen(false)} className="text-dim hover:text-ink" aria-label="Close">
            ✕
          </button>
        </div>
        <div className="flex flex-col gap-3 p-4">
          <p className="text-[10px] leading-relaxed text-faint">
            Executes for real against <code className="text-accent">{model}</code>{" "}
            using your API key, and records every step as it happens.
          </p>
          <label className="flex flex-col gap-1">
            <span className="stencil">Agent task</span>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={3}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void launch();
              }}
              className="resize-y rounded border border-line bg-bg px-2 py-1.5 text-ink"
            />
          </label>

          <div className="flex flex-wrap gap-1.5">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => setPrompt(ex)}
                className="rounded-full border border-line px-2 py-0.5 text-[10px] text-dim hover:border-accent hover:text-accent"
              >
                {ex.length > 44 ? ex.slice(0, 44) + "…" : ex}
              </button>
            ))}
          </div>

          <label className="flex items-center gap-2">
            <span className="stencil">Seed</span>
            <input
              type="number"
              value={seed}
              onChange={(e) => setSeed(Number(e.target.value) || 0)}
              className="w-24 rounded border border-line bg-bg px-2 py-1 text-ink"
            />
            <span className="text-[10px] text-faint">
              passed to the provider; tool replay is exact, LLM replay best-effort
            </span>
          </label>

          <div className="flex justify-end gap-2 pt-1">
            <button
              onClick={() => setOpen(false)}
              className="rounded border border-line px-3 py-1.5 text-dim hover:text-ink"
            >
              Cancel
            </button>
            <button
              onClick={launch}
              disabled={busy || !prompt.trim()}
              className="rounded border border-accent bg-accent-soft px-3 py-1.5 text-accent hover:bg-accent hover:text-bg disabled:opacity-50"
            >
              {busy ? "Recording…" : "Start recording"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
