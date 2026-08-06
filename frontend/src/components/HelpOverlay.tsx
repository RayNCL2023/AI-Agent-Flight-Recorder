/** Keyboard reference overlay. */

import { useStore } from "../store/useStore";

const SHORTCUTS: Array<[string, string]> = [
  ["← / →", "Scrub to previous / next step"],
  ["↑ / ↓", "Switch branch lane"],
  ["F", "Fork from the selected step"],
  ["N", "Start a new run"],
  ["?", "Toggle this reference"],
  ["Esc", "Close dialogs"],
];

export function HelpOverlay() {
  const open = useStore((s) => s.helpOpen);
  const setOpen = useStore((s) => s.setHelpOpen);
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-bg/80 p-4"
      onClick={() => setOpen(false)}
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
    >
      <div
        className="w-full max-w-sm rounded border border-line bg-panel shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-line px-4 py-2">
          <h2 className="stencil">Keyboard</h2>
        </div>
        <dl className="p-4">
          {SHORTCUTS.map(([key, action]) => (
            <div key={key} className="flex items-center justify-between py-1">
              <dt>
                <kbd className="rounded border border-line bg-bg px-1.5 py-0.5 text-[11px] text-accent">
                  {key}
                </kbd>
              </dt>
              <dd className="text-[11px] text-dim">{action}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
