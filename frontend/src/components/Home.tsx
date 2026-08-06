/**
 * Landing page: hero with an animated recorded-trace backdrop, the recorded
 * trace library, and the Live Mode section. This page is the front door of the
 * demo and must make one thing unmistakable: everything here is a recording.
 */

import type { RunListItem } from "../api/types";
import { fmtCost, fmtDuration, fmtTokens } from "../lib/format";
import { useStore } from "../store/useStore";

export function Home() {
  const runs = useStore((s) => s.runs);
  const meta = useStore((s) => s.meta);
  const openRun = useStore((s) => s.openRun);
  const setError = useStore((s) => s.setError);
  const setLauncherOpen = useStore((s) => s.setLauncherOpen);

  const library = runs.filter((r) => r.source === "recorded");
  const liveRuns = runs.filter((r) => r.source === "live");

  const open = (id: string) =>
    openRun(id).catch((err) =>
      setError(err instanceof Error ? err.message : String(err)),
    );

  return (
    <main className="min-h-0 flex-1 overflow-y-auto">
      {/* ------------------------------------------------------------- hero */}
      <section className="relative overflow-hidden border-b border-line">
        <HeroTrace />
        <div className="relative mx-auto flex max-w-5xl flex-col items-start gap-4 px-6 py-16 sm:py-24">
          <span className="stencil rounded-sm border border-line bg-panel px-2 py-1">
            Flight data recorder for LLM agents
          </span>
          <h1 className="max-w-3xl text-3xl font-semibold leading-tight tracking-tight text-ink sm:text-5xl">
            Time-travel debugging for AI agents.
          </h1>
          <p className="max-w-xl text-sm leading-relaxed text-dim sm:text-base">
            Replay, inspect, fork and compare every decision an LLM agent makes.
          </p>
          <p className="max-w-xl text-[12px] leading-relaxed text-dim">
            You are watching <span className="text-ink">recorded executions</span> —
            every reasoning step, tool call and token below was captured once and
            replays deterministically. Nothing on this page is generated live.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <a
              href="#library"
              className="rounded border border-accent bg-accent-soft px-4 py-2 text-[13px] text-accent transition-colors hover:bg-accent hover:text-bg"
            >
              ▶ Open a recording
            </a>
            <a
              href="#live"
              className="rounded border border-line px-4 py-2 text-[13px] text-dim transition-colors hover:border-accent hover:text-ink"
            >
              Live Mode
            </a>
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------------- library */}
      <section id="library" className="mx-auto max-w-5xl px-6 py-10">
        <div className="mb-1 flex items-baseline justify-between">
          <h2 className="stencil">Recorded trace library</h2>
          <span className="stencil !text-[9px]">
            {library.length} recordings · fully offline · $0 per replay
          </span>
        </div>
        <p className="mb-4 max-w-2xl text-[11px] leading-relaxed text-dim">
          Each card is one complete agent execution. Open it to replay the black
          box: scrub the timeline, expand reasoning, inspect tool I/O — then run
          a recorded experiment to fork history and compare the outcomes.
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {library.map((run) => (
            <TraceCard key={run.id} run={run} onOpen={() => open(run.id)} />
          ))}
          {library.length === 0 && (
            <p className="col-span-full rounded border border-line bg-panel p-4 text-[11px] text-dim">
              No recorded traces found. The bundled library loads on server
              start — check that the backend is running and seeded.
            </p>
          )}
        </div>
      </section>

      {/* ------------------------------------------------------------- live */}
      <section id="live" className="mx-auto max-w-5xl px-6 pb-14">
        <h2 className="stencil mb-4">Live Mode</h2>
        {meta?.live_available ? (
          <div className="rounded border border-line bg-panel p-4">
            <p className="text-[12px] text-ink">
              Live Mode is enabled against <code className="text-accent">{meta.model}</code>.
              New runs execute for real and are recorded as they happen.
            </p>
            <button
              onClick={() => setLauncherOpen(true)}
              className="mt-3 rounded border border-accent bg-accent-soft px-4 py-2 text-[13px] text-accent transition-colors hover:bg-accent hover:text-bg"
            >
              ▶ Record a live run
            </button>
            {liveRuns.length > 0 && (
              <div className="mt-4 border-t border-line pt-3">
                <div className="stencil mb-2 !text-[9px]">Your live recordings</div>
                <div className="flex flex-wrap gap-2">
                  {liveRuns.map((r) => (
                    <button
                      key={r.id}
                      onClick={() => open(r.id)}
                      className="rounded border border-line px-2 py-1 text-[11px] text-dim hover:border-accent hover:text-ink"
                    >
                      {r.title}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="rounded border border-line bg-panel p-4">
            <p className="text-[13px] text-warn">Live execution unavailable.</p>
            <p className="mt-2 max-w-2xl text-[11px] leading-relaxed text-dim">
              This demo never fabricates model output, so without an API key
              there is no live agent — and Replay Mode is never silently
              substituted for one. To execute new runs for real, bring your own
              key:
            </p>
            <pre className="mt-3 overflow-x-auto rounded border border-line bg-bg p-3 text-[11px] leading-relaxed text-ink">
{`# backend/.env
AFR_MODE=live
OPENAI_API_KEY=sk-...          # your key — any OpenAI-compatible endpoint
# OPENAI_BASE_URL=...          # optional: vLLM, Ollama, LM Studio, Azure
# LLM_MODEL=gpt-4o-mini        # optional

# then restart the backend`}
            </pre>
            <p className="mt-2 text-[10px] text-faint">
              Keys stay on your server; the browser never sees them.
            </p>
          </div>
        )}
      </section>
    </main>
  );
}

// ------------------------------------------------------------------ trace card

function TraceCard({ run, onOpen }: { run: RunListItem; onOpen: () => void }) {
  return (
    <button
      onClick={onOpen}
      className="trace-card group flex flex-col gap-2.5 rounded border border-line bg-panel p-3.5 text-left transition-colors hover:border-accent"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-[13px] font-semibold text-ink">{run.title}</h3>
        <span className="stencil shrink-0 !text-[8px] text-faint group-hover:text-accent">
          ● REC
        </span>
      </div>
      <p className="min-h-9 text-[11px] leading-relaxed text-dim">
        {run.description}
      </p>
      <div className="flex flex-wrap gap-1">
        {run.tools_used.map((t) => (
          <span
            key={t}
            className="rounded-full border border-line px-1.5 py-0.5 text-[9px] text-dim"
          >
            ⚙ {t}
          </span>
        ))}
        {run.experiments.length > 0 && (
          <span className="rounded-full border border-line px-1.5 py-0.5 text-[9px] text-lane-2">
            ⑂ {run.experiments.length} experiment{run.experiments.length === 1 ? "" : "s"}
          </span>
        )}
      </div>
      <dl className="mt-auto grid grid-cols-4 gap-px overflow-hidden rounded border border-line bg-line text-center">
        <CardStat label="events" value={String(run.stats.events)} />
        <CardStat label="time" value={fmtDuration(run.stats.duration_ms)} />
        <CardStat label="tokens" value={fmtTokens(run.stats.tokens)} />
        <CardStat label="cost" value={fmtCost(run.stats.cost_usd)} />
      </dl>
      <span className="text-[11px] text-accent opacity-70 transition-opacity group-hover:opacity-100">
        ▶ Replay recording
      </span>
    </button>
  );
}

function CardStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-panel px-1 py-1.5">
      <dt className="text-[8px] uppercase tracking-wider text-faint">{label}</dt>
      <dd className="text-[10px] text-ink">{value}</dd>
    </div>
  );
}

// ------------------------------------------------------- animated hero trace

/**
 * Decorative replay of a branching trace: a playhead sweeps two lanes, nodes
 * light up as it passes, and a fork diverges mid-flight. Pure CSS animation,
 * hidden from assistive tech, stilled under prefers-reduced-motion.
 */
function HeroTrace() {
  const mainNodes = [80, 200, 320, 440, 560, 680, 800, 920, 1040, 1130];
  const forkNodes = [560, 680, 800, 920, 1040];
  const laneY = 120;
  const forkY = 230;
  const sweepSeconds = 14;
  const delay = (x: number) => `${(x / 1200) * sweepSeconds}s`;

  return (
    <div aria-hidden className="hero-trace absolute inset-0">
      <svg
        className="h-full w-full"
        viewBox="0 0 1200 320"
        preserveAspectRatio="xMidYMid slice"
      >
        <line x1="0" y1={laneY} x2="1200" y2={laneY} stroke="var(--color-line)" strokeWidth="1.5" />
        <path
          d={`M 440 ${laneY} C 500 ${laneY}, 500 ${forkY}, 560 ${forkY} L 1200 ${forkY}`}
          fill="none"
          stroke="var(--color-line)"
          strokeWidth="1.5"
          strokeDasharray="5 4"
        />
        {mainNodes.map((x) => (
          <circle
            key={`m${x}`}
            className="hero-node"
            style={{ animationDelay: delay(x) }}
            cx={x}
            cy={laneY}
            r="7"
            fill="var(--color-bg)"
            stroke="var(--color-lane-1)"
            strokeWidth="1.5"
          />
        ))}
        {forkNodes.map((x) => (
          <circle
            key={`f${x}`}
            className="hero-node"
            style={{ animationDelay: delay(x) }}
            cx={x}
            cy={forkY}
            r="7"
            fill="var(--color-bg)"
            stroke="var(--color-lane-2)"
            strokeWidth="1.5"
          />
        ))}
        <g className="hero-playhead">
          <line x1="0" y1="0" x2="0" y2="320" stroke="var(--color-accent)" strokeWidth="1.5" opacity="0.9" />
          <rect x="-6" y="-2" width="12" height="12" transform="rotate(45 0 4)" fill="var(--color-bg)" stroke="var(--color-accent)" strokeWidth="1.5" />
        </g>
      </svg>
    </div>
  );
}
