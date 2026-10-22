/**
 * Fork dialog: replay from the selected step, rewriting history.
 *
 * In Replay Mode the first-class path is a *recorded experiment* — a curated
 * fork variant captured with the trace, guaranteed to replay end-to-end.
 * Custom edits remain available, with an explicit statement of what happens
 * when a change leaves recorded coverage: the replay stops honestly.
 */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { ExperimentOut } from "../api/types";
import { selectedEvent, useStore } from "../store/useStore";

export function ForkDialog() {
  const open = useStore((s) => s.forkOpen);
  const setOpen = useStore((s) => s.setForkOpen);
  const run = useStore((s) => s.run);
  const meta = useStore((s) => s.meta);
  const event = useStore(selectedEvent);
  const setError = useStore((s) => s.setError);

  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [toolOutput, setToolOutput] = useState("");
  const [busy, setBusy] = useState(false);

  const rootBranchId = run?.branches.find((b) => !b.parent_branch_id)?.id;
  const isToolResult = event?.type === "tool_result";
  const originalOutput = useMemo(
    () =>
      isToolResult
        ? JSON.stringify((event!.payload as any).output ?? {}, null, 2)
        : "",
    [event, isToolResult],
  );

  useEffect(() => {
    if (open) {
      setName("");
      setPrompt(run?.prompt ?? "");
      setToolOutput(originalOutput);
    }
  }, [open, run?.prompt, originalOutput]);

  if (!open || !run || !event) return null;

  const live = Boolean(meta?.live_available);
  const promptEdited = prompt.trim() !== run.prompt.trim();
  const outputEdited = isToolResult && toolOutput.trim() !== originalOutput.trim();
  const experiments = run.experiments;

  const runExperiment = async (exp: ExperimentOut) => {
    if (!rootBranchId) return;
    setBusy(true);
    try {
      await api.fork(rootBranchId, {
        fork_seq: exp.fork_seq,
        name: exp.title,
        edited_prompt: exp.edited_prompt,
        tool_overrides: exp.tool_overrides,
      });
      useStore.setState({ forkOpen: false, followLive: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const submitCustom = async () => {
    setBusy(true);
    try {
      let overrides: Record<string, Record<string, unknown>> | undefined;
      let forkSeq = promptEdited ? 1 : event.seq;
      if (outputEdited) {
        let parsed: Record<string, unknown>;
        try {
          parsed = JSON.parse(toolOutput);
        } catch {
          throw new Error("Replacement tool output must be valid JSON.");
        }
        overrides = { [event.id]: parsed };
        forkSeq = event.seq + 1; // keep the (rewritten) result, replay after it
      }
      await api.fork(event.branch_id, {
        fork_seq: forkSeq,
        name: name.trim() || undefined,
        edited_prompt: promptEdited ? prompt : undefined,
        tool_overrides: overrides,
      });
      useStore.setState({ forkOpen: false, followLive: true });
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
      aria-label="Fork execution"
    >
      <div
        className="flex max-h-[90vh] w-full max-w-xl flex-col rounded border border-line bg-panel shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-line px-4 py-2">
          <h2 className="stencil">⑂ Fork this recording</h2>
          <button onClick={() => setOpen(false)} className="text-dim hover:text-ink" aria-label="Close">
            ✕
          </button>
        </div>

        <div className="flex flex-col gap-4 overflow-y-auto p-4">
          {experiments.length > 0 && (
            <section>
              <div className="stencil mb-1.5">Recorded experiments</div>
              <p className="mb-2 text-[10px] leading-relaxed text-faint">
                Curated what-ifs captured with this trace. Each replays a real
                recorded divergence end-to-end — guaranteed to complete.
              </p>
              <div className="flex flex-col gap-2">
                {experiments.map((exp) => (
                  <button
                    key={exp.id}
                    onClick={() => runExperiment(exp)}
                    disabled={busy}
                    className="group rounded border border-line bg-panel-2 p-2.5 text-left transition-colors hover:border-accent disabled:opacity-50"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[12px] text-ink">{exp.title}</span>
                      <span className="shrink-0 text-[11px] text-accent opacity-60 group-hover:opacity-100">
                        ⑂ Run
                      </span>
                    </div>
                    <p className="mt-1 text-[10px] leading-relaxed text-dim">
                      {exp.description}
                    </p>
                    <p className="mt-1 text-[9px] text-faint">
                      {exp.edited_prompt
                        ? "edits the prompt · replays from the start"
                        : `replaces a tool output · forks at step #${exp.fork_seq - 1}`}
                    </p>
                  </button>
                ))}
              </div>
            </section>
          )}

          <section>
            <div className="stencil mb-1.5">
              Custom modification — from step #{event.seq}
            </div>
            <p className="mb-2 rounded border border-line bg-bg p-2 text-[10px] leading-relaxed text-dim">
              {live ? (
                <>History before the fork point is inherited; the modified path
                executes live against the model and is recorded as it runs.</>
              ) : (
                <>Replay Mode replays recorded material only. Unedited steps
                reproduce exactly; if your change leaves the recording's
                coverage, the fork stops with{" "}
                <span className="text-warn">
                  “No recorded execution matches this request.”
                </span>{" "}
                — it will never invent a continuation.</>
              )}
            </p>

            <label className="flex flex-col gap-1">
              <span className="stencil">Branch name</span>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={`fork of ${event.type} #${event.seq}`}
                className="rounded border border-line bg-bg px-2 py-1.5 text-ink placeholder:text-faint"
              />
            </label>

            <label className="mt-3 flex flex-col gap-1">
              <span className="stencil">
                Prompt {promptEdited && <em className="text-accent">— edited, replays from start</em>}
              </span>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={3}
                className="resize-y rounded border border-line bg-bg px-2 py-1.5 text-ink"
              />
            </label>

            {isToolResult && (
              <label className="mt-3 flex flex-col gap-1">
                <span className="stencil">
                  Tool output ({String((event.payload as any).tool)}){" "}
                  {outputEdited && <em className="text-accent">— will replace the recorded result</em>}
                </span>
                <textarea
                  value={toolOutput}
                  onChange={(e) => setToolOutput(e.target.value)}
                  rows={6}
                  spellCheck={false}
                  className="resize-y rounded border border-line bg-bg px-2 py-1.5 font-mono text-[11px] text-ink"
                />
              </label>
            )}

            <div className="mt-3 flex items-center justify-end gap-2">
              <button
                onClick={() => setOpen(false)}
                className="rounded border border-line px-3 py-1.5 text-dim hover:text-ink"
              >
                Cancel
              </button>
              <button
                onClick={submitCustom}
                disabled={busy}
                className="rounded border border-accent bg-accent-soft px-3 py-1.5 text-accent hover:bg-accent hover:text-bg disabled:opacity-50"
              >
                {busy ? "Forking…" : "Fork & replay"}
              </button>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
