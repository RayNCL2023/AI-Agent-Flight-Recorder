/**
 * Fork dialog: replay from the selected step, optionally rewriting history —
 * edit the prompt, or (when a tool result is selected) replace its output.
 */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { selectedEvent, useStore } from "../store/useStore";

export function ForkDialog() {
  const open = useStore((s) => s.forkOpen);
  const setOpen = useStore((s) => s.setForkOpen);
  const run = useStore((s) => s.run);
  const event = useStore(selectedEvent);
  const setError = useStore((s) => s.setError);

  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [toolOutput, setToolOutput] = useState("");
  const [busy, setBusy] = useState(false);

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

  const promptEdited = prompt.trim() !== run.prompt.trim();
  const outputEdited = isToolResult && toolOutput.trim() !== originalOutput.trim();

  const submit = async () => {
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
        className="w-full max-w-xl rounded border border-line bg-panel shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-2">
          <h2 className="stencil">⑂ Fork — replay from step #{event.seq}</h2>
          <button onClick={() => setOpen(false)} className="text-dim hover:text-ink" aria-label="Close">
            ✕
          </button>
        </div>

        <div className="flex flex-col gap-3 p-4">
          <p className="text-[11px] leading-relaxed text-dim">
            History before this step is inherited unchanged. Unedited tool calls
            replay from the run cache, so the only divergence will be what you
            change here.
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

          <label className="flex flex-col gap-1">
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
            <label className="flex flex-col gap-1">
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

          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              onClick={() => setOpen(false)}
              className="rounded border border-line px-3 py-1.5 text-dim hover:text-ink"
            >
              Cancel
            </button>
            <button
              onClick={submit}
              disabled={busy}
              className="rounded border border-accent bg-accent-soft px-3 py-1.5 text-accent hover:bg-accent hover:text-bg disabled:opacity-50"
            >
              {busy ? "Forking…" : "Fork & replay"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
