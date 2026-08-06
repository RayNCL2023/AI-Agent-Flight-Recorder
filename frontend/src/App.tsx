import { useEffect } from "react";
import { DiffPanel } from "./components/DiffPanel";
import { ForkDialog } from "./components/ForkDialog";
import { HelpOverlay } from "./components/HelpOverlay";
import { Home } from "./components/Home";
import { Inspector } from "./components/Inspector";
import { LiveRunDialog } from "./components/LiveRunDialog";
import { Timeline } from "./components/Timeline";
import { TopBar } from "./components/TopBar";
import { useKeyboard } from "./hooks/useKeyboard";
import { usePlayback } from "./hooks/usePlayback";
import { useRunStream } from "./hooks/useRunStream";
import { useStore } from "./store/useStore";

export default function App() {
  const view = useStore((s) => s.view);
  const run = useStore((s) => s.run);
  const loadMeta = useStore((s) => s.loadMeta);
  const loadRuns = useStore((s) => s.loadRuns);
  const error = useStore((s) => s.error);
  const setError = useStore((s) => s.setError);
  const setHelpOpen = useStore((s) => s.setHelpOpen);

  useRunStream(run?.id ?? null);
  useKeyboard();
  usePlayback();

  useEffect(() => {
    const report = (err: unknown) =>
      setError(err instanceof Error ? err.message : String(err));
    loadMeta().catch(report);
    loadRuns().catch(report);
  }, [loadMeta, loadRuns, setError]);

  useEffect(() => {
    if (!error) return;
    const t = setTimeout(() => setError(null), 6000);
    return () => clearTimeout(t);
  }, [error, setError]);

  return (
    <div className="flex h-full flex-col">
      <TopBar />

      {view === "trace" && run ? (
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
        <Home />
      )}

      <footer className="flex h-7 shrink-0 items-center justify-between border-t border-line bg-panel px-3">
        <span className="stencil">
          ⏺ black box · every step recorded · nothing fabricated
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

      <LiveRunDialog />
      <ForkDialog />
      <HelpOverlay />
    </div>
  );
}
