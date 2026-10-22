/**
 * Persistent execution-mode badge with an explainer popover. This is the
 * single most important honesty affordance in the UI: at any moment, one
 * glance answers "am I talking to a live model?" — and in Replay Mode the
 * answer is always no.
 */

import { useEffect, useRef, useState } from "react";
import { useStore } from "../store/useStore";

export function ModeBadge() {
  const meta = useStore((s) => s.meta);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!meta) return null;
  const live = meta.live_available;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label="Execution mode details"
        className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] transition-colors ${
          live
            ? "border-err/60 text-err hover:border-err"
            : "border-line text-dim hover:border-accent hover:text-ink"
        }`}
      >
        <span className={live ? "rec-pulse text-err" : "text-lane-1"}>●</span>
        {live ? (
          <span>Live Mode • {meta.model} • executions cost real tokens</span>
        ) : (
          <span>
            Replay Mode • Viewing recorded execution traces • Live AI disabled
          </span>
        )}
        <span className="text-faint">ⓘ</span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="About this mode"
          className="absolute right-0 top-8 z-40 w-80 rounded border border-line bg-panel p-3 shadow-2xl"
        >
          {live ? (
            <>
              <div className="stencil mb-2">Live Mode</div>
              <ul className="flex flex-col gap-1.5 text-[11px] leading-relaxed text-dim">
                <Li>
                  New runs execute against <span className="text-ink">{meta.model}</span>{" "}
                  with your own API key and are recorded as they happen.
                </Li>
                <Li>
                  Every live step lands in the replay caches, so finished runs
                  fork and replay deterministically like any recording.
                </Li>
              </ul>
            </>
          ) : (
            <>
              <div className="stencil mb-2">Why replay?</div>
              <ul className="flex flex-col gap-1.5 text-[11px] leading-relaxed text-dim">
                <Li>
                  The traces here were <span className="text-ink">generated from real
                  agent runs</span> by a recording harness and shipped with the app —
                  nothing you see is produced on the fly.
                </Li>
                <Li>
                  Replay exists for <span className="text-ink">determinism</span>: the
                  same trace renders identically on every visit, every machine.
                </Li>
                <Li>
                  No model is called, so exploring costs{" "}
                  <span className="text-ink">zero API tokens</span>.
                </Li>
                <Li>
                  Editing a prompt or tool output creates a{" "}
                  <span className="text-ink">deterministic fork</span> — a new branch
                  replayed from recorded material, never invented.
                </Li>
                <Li>
                  If a change leaves recorded coverage, the replay{" "}
                  <span className="text-ink">stops and says so</span> instead of
                  fabricating a continuation.
                </Li>
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Li({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex gap-2">
      <span className="text-accent">▸</span>
      <span>{children}</span>
    </li>
  );
}
