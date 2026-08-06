/**
 * Central Zustand store.
 *
 * Timelines are kept per-branch as fully resolved event arrays (inherited +
 * own). Live SSE events are appended and de-duplicated by id; a branch fetch
 * replaces the array wholesale. `freshEventIds` drives entrance/typewriter
 * animation only for events that arrived over the stream, so replaying history
 * never re-animates.
 */

import { create } from "zustand";
import { api } from "../api/client";
import type {
  BranchOut,
  BranchTimeline,
  EventOut,
  RunDetail,
  RunOut,
  StreamMessage,
} from "../api/types";

interface Selection {
  branchId: string | null;
  seq: number | null;
}

interface StoreState {
  runs: RunOut[];
  run: RunDetail | null;
  timelines: Record<string, EventOut[]>;
  freshEventIds: Set<string>;
  selection: Selection;
  followLive: boolean;
  helpOpen: boolean;
  forkOpen: boolean;
  launcherOpen: boolean;
  error: string | null;

  loadRuns: () => Promise<void>;
  openRun: (runId: string) => Promise<void>;
  createRun: (prompt: string, seed?: number) => Promise<void>;
  deleteRun: (runId: string) => Promise<void>;
  refreshBranch: (branchId: string) => Promise<void>;
  handleStream: (msg: StreamMessage) => void;
  select: (branchId: string, seq: number) => void;
  moveSelection: (dSeq: number, dBranch: number) => void;
  setForkOpen: (open: boolean) => void;
  setHelpOpen: (open: boolean) => void;
  setLauncherOpen: (open: boolean) => void;
  setError: (message: string | null) => void;
}

export const useStore = create<StoreState>((set, get) => ({
  runs: [],
  run: null,
  timelines: {},
  freshEventIds: new Set(),
  selection: { branchId: null, seq: null },
  followLive: true,
  helpOpen: false,
  forkOpen: false,
  launcherOpen: false,
  error: null,

  loadRuns: async () => {
    const runs = await api.listRuns();
    set({ runs });
    const { run } = get();
    if (!run && runs.length > 0) await get().openRun(runs[0].id);
  },

  openRun: async (runId) => {
    const run = await api.getRun(runId);
    const timelines: Record<string, EventOut[]> = {};
    const results = await Promise.all(
      run.branches.map((b) => api.branchTimeline(b.id)),
    );
    for (const t of results) timelines[t.branch.id] = t.events;
    const root = run.branches.find((b) => !b.parent_branch_id);
    const rootEvents = root ? (timelines[root.id] ?? []) : [];
    set({
      run,
      timelines,
      freshEventIds: new Set(),
      followLive: run.status === "running" || run.status === "pending",
      selection: root
        ? { branchId: root.id, seq: rootEvents.at(-1)?.seq ?? null }
        : { branchId: null, seq: null },
    });
  },

  createRun: async (prompt, seed = 42) => {
    const run = await api.createRun(prompt, seed);
    set((s) => ({ runs: [toRunOut(run), ...s.runs], launcherOpen: false }));
    await get().openRun(run.id);
    set({ followLive: true });
  },

  deleteRun: async (runId) => {
    await api.deleteRun(runId);
    const runs = get().runs.filter((r) => r.id !== runId);
    set({ runs });
    if (get().run?.id === runId) {
      set({ run: null, timelines: {}, selection: { branchId: null, seq: null } });
      if (runs.length > 0) await get().openRun(runs[0].id);
    }
  },

  refreshBranch: async (branchId) => {
    const t: BranchTimeline = await api.branchTimeline(branchId);
    set((s) => ({ timelines: { ...s.timelines, [branchId]: t.events } }));
  },

  handleStream: (msg) => {
    const { run } = get();
    if (!run) return;

    if (msg.kind === "run_update") {
      if (msg.run.id !== run.id) return;
      set((s) => ({
        run: s.run ? { ...s.run, ...msg.run, branches: s.run.branches } : null,
        runs: s.runs.map((r) => (r.id === msg.run.id ? msg.run : r)),
      }));
      return;
    }

    if (msg.kind === "branch_update") {
      if (msg.branch.run_id !== run.id) return;
      set((s) => {
        if (!s.run) return s;
        const known = s.run.branches.some((b) => b.id === msg.branch.id);
        const branches = known
          ? s.run.branches.map((b) => (b.id === msg.branch.id ? msg.branch : b))
          : [...s.run.branches, msg.branch];
        return { run: { ...s.run, branches } };
      });
      // A brand-new fork needs its inherited history fetched once.
      if (!(msg.branch.id in get().timelines)) {
        void get().refreshBranch(msg.branch.id);
      }
      return;
    }

    // kind === "event"
    const ev = msg.event;
    if (ev.run_id !== run.id) return;
    set((s) => {
      const existing = s.timelines[ev.branch_id] ?? [];
      if (existing.some((e) => e.id === ev.id)) return s;
      const fresh = new Set(s.freshEventIds);
      fresh.add(ev.id);
      const next = {
        ...s.timelines,
        [ev.branch_id]: [...existing, ev].sort((a, b) => a.seq - b.seq),
      };
      const sel =
        s.followLive || s.selection.branchId === null
          ? { branchId: ev.branch_id, seq: ev.seq }
          : s.selection;
      return { timelines: next, freshEventIds: fresh, selection: sel };
    });
  },

  select: (branchId, seq) =>
    set({ selection: { branchId, seq }, followLive: false }),

  moveSelection: (dSeq, dBranch) => {
    const { run, timelines, selection } = get();
    if (!run || !selection.branchId) return;
    const branches = sortedBranches(run.branches);
    let branchIdx = branches.findIndex((b) => b.id === selection.branchId);
    if (branchIdx === -1) return;

    if (dBranch !== 0) {
      branchIdx = clamp(branchIdx + dBranch, 0, branches.length - 1);
      const events = timelines[branches[branchIdx].id] ?? [];
      const nearest = nearestSeq(events, selection.seq ?? 1);
      set({
        selection: { branchId: branches[branchIdx].id, seq: nearest },
        followLive: false,
      });
      return;
    }

    const events = timelines[selection.branchId] ?? [];
    if (events.length === 0) return;
    const idx = events.findIndex((e) => e.seq === selection.seq);
    const nextIdx = clamp((idx === -1 ? 0 : idx) + dSeq, 0, events.length - 1);
    set({
      selection: { branchId: selection.branchId, seq: events[nextIdx].seq },
      followLive: false,
    });
  },

  setForkOpen: (forkOpen) => set({ forkOpen }),
  setHelpOpen: (helpOpen) => set({ helpOpen }),
  setLauncherOpen: (launcherOpen) => set({ launcherOpen }),
  setError: (error) => set({ error }),
}));

// ------------------------------------------------------------------ selectors

export function sortedBranches(branches: BranchOut[]): BranchOut[] {
  return [...branches].sort(
    (a, b) =>
      Number(Boolean(a.parent_branch_id)) - Number(Boolean(b.parent_branch_id)) ||
      a.created_at.localeCompare(b.created_at),
  );
}

export function selectedEvent(s: {
  timelines: Record<string, EventOut[]>;
  selection: Selection;
}): EventOut | null {
  if (!s.selection.branchId || s.selection.seq === null) return null;
  return (
    (s.timelines[s.selection.branchId] ?? []).find(
      (e) => e.seq === s.selection.seq,
    ) ?? null
  );
}

export function branchStats(events: EventOut[]) {
  return {
    events: events.length,
    tokensIn: events.reduce((n, e) => n + e.tokens_in, 0),
    tokensOut: events.reduce((n, e) => n + e.tokens_out, 0),
    costUsd: events.reduce((n, e) => n + e.cost_usd, 0),
    durationMs: events.reduce((n, e) => n + e.duration_ms, 0),
  };
}

function toRunOut(run: RunDetail): RunOut {
  const { branches: _branches, ...rest } = run;
  return rest;
}

function clamp(n: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, n));
}

function nearestSeq(events: EventOut[], target: number): number | null {
  if (events.length === 0) return null;
  let best = events[0].seq;
  for (const e of events) {
    if (Math.abs(e.seq - target) < Math.abs(best - target)) best = e.seq;
  }
  return best;
}
