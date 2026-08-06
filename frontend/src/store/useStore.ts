/**
 * Central Zustand store.
 *
 * Views: "home" is the landing page + recorded trace library; "trace" is the
 * replay workspace for one run. `meta` mirrors /api/meta — the UI must always
 * reflect the true execution mode and never pretend live AI is available.
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
  Meta,
  RunDetail,
  RunListItem,
  StreamMessage,
} from "../api/types";

interface Selection {
  branchId: string | null;
  seq: number | null;
}

export type PlaybackSpeed = 1 | 2 | 4;

interface StoreState {
  view: "home" | "trace";
  meta: Meta | null;
  runs: RunListItem[];
  run: RunDetail | null;
  timelines: Record<string, EventOut[]>;
  freshEventIds: Set<string>;
  selection: Selection;
  followLive: boolean;
  playing: boolean;
  speed: PlaybackSpeed;
  helpOpen: boolean;
  forkOpen: boolean;
  launcherOpen: boolean;
  error: string | null;

  loadMeta: () => Promise<void>;
  loadRuns: () => Promise<void>;
  openRun: (runId: string) => Promise<void>;
  goHome: () => void;
  createRun: (prompt: string, seed?: number) => Promise<void>;
  deleteRun: (runId: string) => Promise<void>;
  refreshBranch: (branchId: string) => Promise<void>;
  handleStream: (msg: StreamMessage) => void;
  select: (branchId: string, seq: number) => void;
  moveSelection: (dSeq: number, dBranch: number) => void;
  setPlaying: (playing: boolean) => void;
  cycleSpeed: () => void;
  setForkOpen: (open: boolean) => void;
  setHelpOpen: (open: boolean) => void;
  setLauncherOpen: (open: boolean) => void;
  setError: (message: string | null) => void;
}

export const useStore = create<StoreState>((set, get) => ({
  view: "home",
  meta: null,
  runs: [],
  run: null,
  timelines: {},
  freshEventIds: new Set(),
  selection: { branchId: null, seq: null },
  followLive: false,
  playing: false,
  speed: 1,
  helpOpen: false,
  forkOpen: false,
  launcherOpen: false,
  error: null,

  loadMeta: async () => {
    set({ meta: await api.getMeta() });
  },

  loadRuns: async () => {
    set({ runs: await api.listRuns() });
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
      view: "trace",
      run,
      timelines,
      freshEventIds: new Set(),
      playing: false,
      followLive: run.status === "running" || run.status === "pending",
      selection: root
        ? { branchId: root.id, seq: rootEvents[0]?.seq ?? null }
        : { branchId: null, seq: null },
    });
  },

  goHome: () => {
    set({
      view: "home",
      run: null,
      timelines: {},
      playing: false,
      selection: { branchId: null, seq: null },
    });
    void get().loadRuns();
  },

  createRun: async (prompt, seed = 42) => {
    const run = await api.createRun(prompt, seed);
    await get().loadRuns();
    set({ launcherOpen: false });
    await get().openRun(run.id);
    set({ followLive: true });
  },

  deleteRun: async (runId) => {
    await api.deleteRun(runId);
    const runs = get().runs.filter((r) => r.id !== runId);
    set({ runs });
    if (get().run?.id === runId) get().goHome();
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
        runs: s.runs.map((r) => (r.id === msg.run.id ? { ...r, ...msg.run } : r)),
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

  setPlaying: (playing) => set({ playing, followLive: false }),
  cycleSpeed: () =>
    set((s) => ({ speed: s.speed === 1 ? 2 : s.speed === 2 ? 4 : 1 })),

  setForkOpen: (forkOpen) => set({ forkOpen, ...(forkOpen ? { playing: false } : {}) }),
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
