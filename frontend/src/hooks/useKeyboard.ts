/** Global keyboard shortcuts. Inactive while typing in inputs or dialogs. */

import { useEffect } from "react";
import { useStore } from "../store/useStore";

export function useKeyboard() {
  const moveSelection = useStore((s) => s.moveSelection);
  const setForkOpen = useStore((s) => s.setForkOpen);
  const setHelpOpen = useStore((s) => s.setHelpOpen);
  const setLauncherOpen = useStore((s) => s.setLauncherOpen);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const typing =
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT" ||
        target.isContentEditable;

      if (e.key === "Escape") {
        setForkOpen(false);
        setHelpOpen(false);
        setLauncherOpen(false);
        return;
      }
      if (typing) return;

      if (e.key === " ") {
        const { view, playing, setPlaying } = useStore.getState();
        if (view === "trace") {
          e.preventDefault();
          setPlaying(!playing);
        }
        return;
      }

      switch (e.key) {
        case "ArrowLeft":
          e.preventDefault();
          moveSelection(-1, 0);
          break;
        case "ArrowRight":
          e.preventDefault();
          moveSelection(1, 0);
          break;
        case "ArrowUp":
          e.preventDefault();
          moveSelection(0, -1);
          break;
        case "ArrowDown":
          e.preventDefault();
          moveSelection(0, 1);
          break;
        case "f":
        case "F":
          setForkOpen(true);
          break;
        case "n":
        case "N":
          setLauncherOpen(true);
          break;
        case "?":
          setHelpOpen(true);
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [moveSelection, setForkOpen, setHelpOpen, setLauncherOpen]);
}
