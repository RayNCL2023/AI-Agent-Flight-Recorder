import { useEffect } from "react";
import { DiffPanel } from "./components/DiffPanel";
import { ForkDialog } from "./components/ForkDialog";
import { HelpOverlay } from "./components/HelpOverlay";
import { Inspector } from "./components/Inspector";
import { RunLauncher } from "./components/RunLauncher";
import { Timeline } from "./components/Timeline";
import { TopBar } from "./components/TopBar";
import { useKeyboard } from "./hooks/useKeyboard";
import { useRunStream } from "./hooks/useRunStream";
import { useStore } from "./store/useStore";

export default function App() {
  const run = useStore((s) => s.run);
  const loadRuns = useStore((s) => s.loadRuns);
  const error = useStore((s) => s.error);
  const setError = useStore((s) => s.setError);
  const setHelpOpen = useStore((s) => s.setHelpOpen);
  const setLauncherOpen = useStore((s) => s.setLauncherOpen);

  useRunStream(run?.id ?? null);
  useKeyboard();

  useEffect(() => {
    loadRuns().catch((err) =>
      setError(err instanceof Error ? err.message : String(err)),
    );
  }, [loadRuns, setError]);

  useEffect(() => {
    if (!error) return;
    const t = setTimeout(() => setError(null), 6000);
    return () => clearTimeout(t);
  }, [error, setError]);

  return (
    <div className="flex h-full flex-col">
      <TopBar />

      {run ? (
        <main className="flex min-h-0 flex-1 flex-col">
          <div className="min-h-0 basis-[42%]">
            <Timeline />
          </div>
          <div className="flex min-h-0 flex-1 flex-col md:flex-row">
            <Inspector />
            <DiffPanel />
          </div>
        </main>
      ) : (
        <EmptyState onStart={() => setLauncherOpen(true)} />
      )}

      <footer className="flex h-7 shrink-0 items-center justify-between border-t border-line bg-panel px-3">
        <span className="stencil">
          ⏺ black box · every step recorded · nothing erased
        </span>
        <button onClick={() => setHelpOpen(true)} className="stencil hover:text-ink">
          ? keyboard
        </button>
      </footer>

      {error && (
        <div
          role="alert"
          className="fixed bottom-10 left-1/2 z-50 -translate-x-1/2 rounded border border-err bg-panel px-4 py-2 text-[11px] text-err shadow-2xl"
        >
          {error}
        </div>
      )}

      <RunLauncher />
      <ForkDialog />
      <HelpOverlay />
    </div>
  );
}

function EmptyState({ onStart }: { onStart: () => void }) {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4">
      <div className="flex h-16 w-16 items-center justify-center rounded bg-accent text-3xl text-bg">
        ⏺
      </div>
      <div className="text-center">
        <h1 className="text-sm text-ink">No flights recorded yet</h1>
        <p className="mt-1 max-w-sm text-[11px] leading-relaxed text-dim">
          Start a run and every LLM call, thought and tool invocation will land
          on the timeline — then scrub back, rewrite history, and fork.
        </p>
      </div>
      <button
        onClick={onStart}
        className="rounded border border-accent bg-accent-soft px-4 py-2 text-accent transition-colors hover:bg-accent hover:text-bg"
      >
        ▶ Record first run
      </button>
    </main>
  );
}
