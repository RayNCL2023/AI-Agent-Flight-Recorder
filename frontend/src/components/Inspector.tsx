/**
 * Step inspector: everything recorded about the selected event, plus the
 * entry points into forking (edit prompt / replace tool output / replay).
 */

import type { EventOut } from "../api/types";
import { EVENT_GLYPH, EVENT_TINT, fmtCost, fmtMs, fmtTime, fmtTokens } from "../lib/format";
import { selectedEvent, useStore } from "../store/useStore";
import { Typewriter } from "./Typewriter";

export function Inspector() {
  const run = useStore((s) => s.run);
  const event = useStore(selectedEvent);
  const freshEventIds = useStore((s) => s.freshEventIds);
  const setForkOpen = useStore((s) => s.setForkOpen);
  const branch = useStore((s) =>
    s.run?.branches.find((b) => b.id === s.selection.branchId),
  );

  if (!run || !event) {
    return (
      <Panel title="Step inspector">
        <p className="p-4 text-dim">
          Select an event on the timeline to inspect it. Use ← → to scrub, ↑ ↓
          to switch branches.
        </p>
      </Panel>
    );
  }

  const canFork =
    branch && branch.status !== "running" && branch.status !== "pending";
  const fresh = freshEventIds.has(event.id);

  return (
    <Panel
      title="Step inspector"
      right={
        <button
          onClick={() => setForkOpen(true)}
          disabled={!canFork}
          title={canFork ? "Fork from this step (F)" : "Wait for the branch to settle"}
          className="rounded border border-accent px-2 py-0.5 text-[11px] text-accent transition-colors hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-40"
        >
          ⑂ Fork here
        </button>
      }
    >
      <div className="flex flex-col gap-3 overflow-y-auto p-3">
        <header className="flex shrink-0 items-center gap-2">
          <span
            className="flex h-8 w-8 items-center justify-center rounded-full border text-sm"
            style={{ borderColor: EVENT_TINT[event.type], color: EVENT_TINT[event.type] }}
          >
            {EVENT_GLYPH[event.type]}
          </span>
          <div>
            <div className="text-sm text-ink">{event.name}</div>
            <div className="text-[10px] text-dim">
              step #{event.seq} · {event.type} · {fmtTime(event.ts)}
              {Boolean(event.meta.replayed) && (
                <span className="ml-2 rounded-sm border border-line px-1 py-px text-[8px] uppercase tracking-wider text-lane-1">
                  replayed from recording
                </span>
              )}
            </div>
          </div>
        </header>

        <dl className="grid shrink-0 grid-cols-4 gap-px overflow-hidden rounded border border-line bg-line text-center">
          <Metric label="latency" value={fmtMs(event.duration_ms)} />
          <Metric label="tok in" value={fmtTokens(event.tokens_in)} />
          <Metric label="tok out" value={fmtTokens(event.tokens_out)} />
          <Metric label="cost" value={fmtCost(event.cost_usd)} />
        </dl>

        <EventBody event={event} fresh={fresh} />

        <details className="group">
          <summary className="stencil cursor-pointer select-none list-none">
            ▸ Raw event <span className="normal-case">(span {event.span_id.slice(0, 8)})</span>
          </summary>
          <pre className="mt-2 overflow-x-auto rounded border border-line bg-bg p-2 text-[11px] leading-relaxed text-dim">
            {JSON.stringify(event, null, 2)}
          </pre>
        </details>
      </div>
    </Panel>
  );
}

function EventBody({ event, fresh }: { event: EventOut; fresh: boolean }) {
  const p = event.payload as Record<string, any>;
  switch (event.type) {
    case "run_started":
      return (
        <Block label="Prompt">
          <p className="whitespace-pre-wrap text-ink">{String(p.prompt ?? "")}</p>
          <p className="mt-2 text-[10px] text-dim">
            model {String(p.model)} · seed {String(p.seed)}
          </p>
          {Boolean(p.system_prompt) && (
            <details className="mt-2">
              <summary className="stencil cursor-pointer select-none list-none">
                ▸ System prompt
              </summary>
              <p className="mt-1 whitespace-pre-wrap rounded border border-line bg-bg p-2 text-[11px] leading-relaxed text-dim">
                {String(p.system_prompt)}
              </p>
            </details>
          )}
        </Block>
      );
    case "reasoning":
      return (
        <Block label="Reasoning">
          <p className="whitespace-pre-wrap italic text-dim">{String(p.text ?? "")}</p>
        </Block>
      );
    case "llm_message":
      return (
        <Block label="Assistant message">
          {p.content && <p className="whitespace-pre-wrap text-ink">{String(p.content)}</p>}
          {(p.tool_calls as any[] | undefined)?.map((tc) => (
            <code key={tc.id} className="mt-1 block rounded bg-bg px-2 py-1 text-[11px] text-lane-0">
              {tc.name}({JSON.stringify(tc.arguments)})
            </code>
          ))}
        </Block>
      );
    case "tool_call":
      return (
        <Block label={`Tool call — ${String(p.tool)}`}>
          <pre className="overflow-x-auto text-[11px] text-ink">
            {JSON.stringify(p.arguments, null, 2)}
          </pre>
        </Block>
      );
    case "tool_result":
      return (
        <Block
          label={`Tool result — ${String(p.tool)}${p.cached ? " · cached replay" : ""}`}
        >
          <pre className="overflow-x-auto text-[11px] text-ink">
            {JSON.stringify(p.output, null, 2)}
          </pre>
          <p className="mt-2 text-[10px] text-dim">
            Fork from the next step to replace this output with your own.
          </p>
        </Block>
      );
    case "retry":
      return (
        <Block label="Retry">
          <p className="text-warn">
            Attempt {String(p.attempt)}/{String(p.of)} of {String(p.tool)}
          </p>
        </Block>
      );
    case "error":
      return (
        <Block label="Error">
          <p className="whitespace-pre-wrap text-err">{String(p.error ?? "")}</p>
        </Block>
      );
    case "completion":
      return (
        <Block label="Final answer">
          <p className="whitespace-pre-wrap text-ink">
            <Typewriter text={String(p.content ?? "")} animate={fresh} />
          </p>
        </Block>
      );
    case "replay_miss":
      return <ReplayMissBlock detail={String(p.detail ?? "")} />;
  }
}

/**
 * The honest stop: replay left recorded coverage. Nothing was fabricated;
 * point the user at the recorded experiments that do replay end-to-end.
 */
function ReplayMissBlock({ detail }: { detail: string }) {
  const setForkOpen = useStore((s) => s.setForkOpen);
  const experiments = useStore((s) => s.run?.experiments ?? []);
  return (
    <div className="shrink-0 rounded border border-warn/50 bg-panel-2 p-2.5">
      <div className="stencil mb-1.5 !text-warn">Replay stopped</div>
      <p className="text-[13px] text-ink">
        No recorded execution matches this request.
      </p>
      <p className="mt-2 text-[11px] leading-relaxed text-dim">{detail}</p>
      {experiments.length > 0 && (
        <button
          onClick={() => setForkOpen(true)}
          className="mt-3 rounded border border-line px-2.5 py-1 text-[11px] text-dim transition-colors hover:border-accent hover:text-accent"
        >
          ⑂ Browse {experiments.length} recorded experiment
          {experiments.length === 1 ? "" : "s"} that replay end-to-end
        </button>
      )}
    </div>
  );
}

function Panel({
  title,
  right,
  children,
}: {
  title: string;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col bg-panel">
      <div className="flex h-8 shrink-0 items-center justify-between border-b border-line px-3">
        <h2 className="stencil">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-panel p-1.5">
      <dt className="text-[9px] uppercase tracking-wider text-dim">{label}</dt>
      <dd className="text-[11px] text-ink">{value}</dd>
    </div>
  );
}

function Block({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="shrink-0 rounded border border-line bg-panel-2 p-2.5">
      <div className="stencil mb-1.5">{label}</div>
      {children}
    </div>
  );
}
