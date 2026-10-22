# ⏺ Agent Flight Recorder

**Time-travel debugging for AI agents.** Replay, inspect, fork and compare
every decision an LLM agent makes.

This is an **AI observability demo built on replay, not a chatbot**. Everything
you see — reasoning, tool calls, tool outputs, final answers, tokens, latency,
cost — comes from **recorded execution traces** that replay deterministically.
The application never fabricates model output: in Replay Mode no LLM is called
at all, and any request that leaves recorded coverage stops with an explicit
*"No recorded execution matches this request."*

Real flight recorders are international orange so they can be found in the
wreckage. This one is for finding out why your agent crashed.

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ⏺ AGENT FLIGHT RECORDER   ⌂ Library   ● Replay Mode • recorded • no AI  │
├──────────────────────────────────────────────────────────────────────────┤
│ TIMELINE   ⏮ ▶ ⏭ 1×  ──────●─────────────          3 branches · 15 steps│
│ main        ▶──…──◆──⚙──⛁──…──◆──⚙──⛁──■           2.1k tok · $0.0007   │
│ storm-fork              ╰⛁──…──⚙──⛁──■             1.4k tok · $0.0004   │
├──────────────────────────────┬───────────────────────────────────────────┤
│ STEP INSPECTOR   [⑂ Fork]    │ DIVERGENCE                                │
│ #9 tool_result — weather     │ verdict: SUCCESS · recorded post-mortem   │
│ replayed from recording      │ = shared history   ≠ final answer         │
│ {"condition":"thunderstorms"}│ word diff + why the behaviour changed     │
└──────────────────────────────┴───────────────────────────────────────────┘
```

## Two modes, honestly separated

- **Replay Mode (default)** — the public demo. A persistent badge reads
  *"Replay Mode • Viewing recorded execution traces • Live AI disabled"*.
  You browse a library of recorded traces, replay them like a black box,
  and fork them along recorded experiment paths. Zero API keys, zero cost,
  bit-for-bit reproducible.
- **Live Mode (bring your own key)** — set `AFR_MODE=live` and
  `OPENAI_API_KEY`, and new runs execute for real against any
  OpenAI-compatible endpoint while being recorded. Without a key, the app
  says **"Live execution unavailable."** and explains how to enable it —
  it never silently downgrades into replay or any offline generator.

## Quickstart

**Backend** (Python 3.11+):

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate      # Windows · use `source .venv/bin/activate` on unix
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**Frontend** (Node 20+):

```bash
cd frontend
npm install
npm run dev                 # http://localhost:5173  (proxies /api → :8000)
```

**Or Docker:** `docker compose up --build` → UI at `http://localhost:3000`.

The recorded trace library loads automatically on first start. For Live Mode,
copy `.env.example` → `backend/.env`, set `AFR_MODE=live` and your key.

> Upgrading from a pre-replay checkout? Delete `backend/data/*.db*` once —
> old databases contain runs from the removed offline generator.

## Using the demo

1. Pick a card in the **trace library** (research, comparison, debugging,
   trip-planning, summarisation) and hit **▶ Replay**.
2. Watch the recording: **Space** plays/pauses, the slider scrubs, `← →`
   step, `↑ ↓` switch branch lanes, clicking any node jumps to it. Every
   step exposes payload, tokens, latency, cost and the raw event JSON.
3. Press **F** to fork:
   - **Recorded experiments** are curated what-ifs shipped with the trace
     (change the research target, erase the search evidence, storm the
     forecast, rewrite the log, control-replay). They replay end-to-end and
     arrive with a recorded post-mortem of *why* the behaviour changed.
   - **Custom edits** replay whatever recorded coverage they keep. Leave
     coverage and the branch stops honestly with a `replay_miss` event —
     nothing is ever invented.
4. The **Divergence** panel aligns the fork against its parent: step diff,
   word-level answer diff, token/latency/cost deltas per lane, and a verdict
   whose provenance is always labeled (*recorded post-mortem*, *heuristic
   analysis*, or *LLM judge* in Live Mode).
5. **⇩ Export** downloads the full bundle (events + both replay caches);
   `POST /api/runs/import` restores it with replay intact.

## Architecture

```
frontend  React 18 · TypeScript · Vite · Zustand · Tailwind v4
   │  typed REST                       SSE stream
   ▼                                     ▼
backend   FastAPI ── engine ── llm-cache ── (Live Mode only: OpenAI-compat LLM)
   │          │        └── tool-cache ── tools: web_search · calculator · file_reader · weather
   │          └── recorder ──► immutable event log ──► SSE bus
   ▼
SQLite (SQLAlchemy 2.0) — runs · branches · events · tool_cache · llm_cache
```

### The replay model

A trace is an **immutable, append-only event log** plus two **replay caches**:

- **Tool cache** — the first execution of every `(tool, args)` pair in a run
  is stored; replays resolve tool calls from this cache, byte-identically.
- **LLM cache** — every completion is stored under
  `sha256(model + seed + full conversation state)`. Replaying a branch walks
  the same conversation states and resolves each LLM step from the cache.

Forking rebuilds the conversation from the event log up to the fork point
(applying your prompt edit / tool-output overrides), then resumes the engine
loop. Unedited states hash identically → cache hits → exact reproduction.
Edited states either follow another recorded path (a shipped experiment) or
miss the cache — and in Replay Mode a miss records a **`replay_miss`** event
and fails the branch instead of generating anything:

```
conversation state ──hash──► llm_cache ──hit──► recorded completion (exact)
                                  │
                                 miss
                                  ├── Live Mode: call the model, record result
                                  └── Replay Mode: replay_miss — honest stop
```

### Event schema (OpenTelemetry-inspired)

Every event: `id · run_id · branch_id · seq · parent_event_id · trace_id ·
span_id · type · name · ts · duration_ms · payload · tokens_in · tokens_out ·
cost_usd · meta`. Types: `run_started · reasoning · llm_message · tool_call ·
tool_result · retry · error · completion · replay_miss`. Events form a causal
chain (`parent_event_id`) inside a branch; branches form a tree per run.
Nothing is ever updated in place.

**Zero-copy forks** — a branch stores `parent_branch_id + fork_seq`; shared
history is *inherited*, not duplicated. A branch's effective history = walk
the ancestor chain, take each ancestor's events below the fork point, then
its own events (`backend/app/agent/replay.py`).

### Deterministic replay strategy

| Source of nondeterminism | Pinned by |
|---|---|
| Tool outputs | run-scoped tool cache (first write wins) |
| LLM completions | run-scoped LLM cache keyed by conversation-state hash |
| Randomness in tools | seeded from `run.seed` |
| Prompts | versioned in the immutable event log; edits create forks |
| Model identity | recorded per run/event; part of the cache key |
| Event identity | stable ids preserved through export/import |

The bundled *"Control replay (determinism proof)"* experiment demonstrates the
guarantee live: fork with no edits, get the identical event sequence back.

### Where the traces come from

The library bundles in `backend/app/traces/` are **curated recordings**
produced by `backend/scripts/record_fixtures.py`: it drives the *real* engine
(real recorder, real tools, real caches, real wall-clock timing) over scripted
agent turns, records each experiment variant, then **verifies every experiment
replays end-to-end through the production no-LLM replay path** before writing
the bundle. The runs are honest recordings of a scripted agent (model id
`scripted-demo-agent`) — not captures of a frontier model, and the UI never
claims otherwise. Recording from a real model is the same pipeline: run in
Live Mode and export, or adapt the harness to pass a live provider.

### Backend layout

```
backend/app/
├── main.py            FastAPI app, /api/meta, lifespan (init + seed library)
├── config.py          pydantic-settings; AFR_MODE replay|live
├── db.py              engine/session, SQLite WAL, additive column migrations
├── models.py          Run · Branch · Event · ToolCacheEntry · LLMCacheEntry
├── schemas.py         typed API contract (mirrored in src/api/types.ts)
├── events.py          event/status/label vocabulary (incl. replay_miss)
├── pricing.py         per-model $/token tables → cost per event
├── bundles.py         v2 bundle import + library seeding
├── bus.py             asyncio pub/sub → SSE
├── agent/
│   ├── engine.py      plan→act→observe loop; cache-first; honest replay_miss
│   ├── llm.py         OpenAICompatProvider (Live Mode only) — no mock exists
│   ├── llm_cache.py   completion cache keyed by conversation-state hash
│   ├── cache.py       tool-output cache
│   ├── scripted.py    ScriptedProvider for the recording harness/tests only
│   ├── recorder.py    append-only event writer + publisher
│   ├── replay.py      effective history · fork creation · branch diff
│   └── tools/         calculator · web_search (offline corpus) · file_reader · weather
├── analysis/
│   └── analyzer.py    verdicts with provenance: recorded | heuristic | llm
├── scripts/record_fixtures.py   recording harness (writes app/traces/)
└── api/               runs (gated) · branches · stream (SSE)
```

### API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/meta` | mode, live availability, model, version |
| `GET` | `/api/runs` | trace library with aggregate stats |
| `POST` | `/api/runs` | start a **live** run — 409 with instructions otherwise |
| `GET`/`DELETE` | `/api/runs/{id}` | detail / delete (recorded traces are immutable) |
| `GET` | `/api/runs/{id}/export` | full v2 bundle (events + replay caches) |
| `POST` | `/api/runs/import` | restore a bundle, replay intact |
| `GET` | `/api/branches/{id}/timeline` | resolved events + token/cost stats |
| `POST` | `/api/branches/{id}/fork` | fork at `fork_seq` with optional overrides |
| `GET` | `/api/branches/{id}/diff` | aligned diff vs parent (or `?against=`) |
| `GET` | `/api/stream/runs/{id}` | SSE: `event` / `branch_update` / `run_update` |

## Why replay for a public demo?

1. **Honesty.** A demo backed by a canned "mock model" *pretends* to be an
   agent and will eventually lie to someone. A replay demo shows real recorded
   executions and says so on every screen.
2. **Determinism.** Every visitor sees the same trace, every time, on any
   machine — which is precisely the property the product exists to provide.
3. **Zero cost & zero keys.** No API spend, no rate limits, no leaked
   credentials, nothing to abuse.
4. **The failure mode is a feature.** "No recorded execution matches this
   request" isn't an apology — it's the observability pitch: the system knows
   exactly what it has evidence for.

## Limitations & trade-offs

- **Replay Mode cannot answer arbitrary questions** — by design. Free-form
  forks stop at the edge of recorded coverage rather than hallucinate.
- **Live-mode LLM determinism is best-effort** (temperature 0 + `seed`);
  tool replay is exact either way. A replayed fork of a live run is exact
  because its completions were cached at record time.
- **Recorded latencies** are shown for replayed steps (labeled *replayed from
  recording*); replay itself is near-instant.
- **Error/retry events replay as their cached outcome**: the failed output is
  cached, so forks reproduce the failure result without re-recording the
  retry choreography.
- **The offline search corpus is small and hand-curated** — it is labeled
  `offline_corpus` in every result and is not live web search.
- **SQLite + in-process SSE bus** keep ops trivial for a demo; a multi-node
  deployment would swap in Postgres and a real broker.

## Future Live Mode work

- Per-session BYOK (key in a request header, never stored) instead of
  server-side env config.
- Anthropic/native provider adapters beyond the OpenAI-compatible surface.
- Streaming token-level events during live runs.
- Regression replay suite: assert a forked fix stays fixed across seeds.

## Tests

```bash
cd backend && python -m pytest        # engine replay honesty, library, API gating, diff, tools
cd frontend && npm run build          # tsc --noEmit + production build
```

The suite covers: LLM-cache key stability, scripted recording → cache
population, **control replay reproducing the recording with no provider**,
honest `replay_miss` on unrecorded states (engine and API level), mode
gating (409s), library seeding with stats, experiment forks reaching their
recorded divergence with recorded post-mortems, v2 export/import round-trips,
diff alignment, calculator sandboxing and tool determinism.

## Keyboard

`Space` play/pause · `← →` scrub · `↑ ↓` switch branch · `F` fork ·
`?` help · `Esc` close.

## License

MIT
