# ⏺ Agent Flight Recorder

**A time-travel debugger for LLM agents.** Every execution step — LLM message,
reasoning, tool call, tool result, retry, error, completion — is recorded as an
immutable event on a branching timeline. Scrub to any step, rewrite history
(edit the prompt, replace a tool output), hit **Fork**, and watch the replay
diverge in a new lane beside the original.

Real flight recorders are international orange so they can be found in the
wreckage. This one is for finding out why your agent crashed.

```
┌──────────────────────────────────────────────────────────────────────┐
│ ⏺ AGENT FLIGHT RECORDER      [run ▾]  ▶ New run     ● RUNNING $0.003 │
├──────────────────────────────────────────────────────────────────────┤
│ main        ▶──◆──⚙──⛁──◆──⚙──⛁──■           1.2k tok · $0.0004     │
│ what-if      ╰⚙──⛁──◆──■                      0.8k tok · $0.0002     │
├──────────────────────────────┬───────────────────────────────────────┤
│ STEP INSPECTOR   [⑂ Fork]    │ DIVERGENCE                            │
│ #4 tool_result — calculator  │ verdict: SUCCESS                      │
│ latency 2ms · 0 tok · $0     │ = #1 run started    ≠ #5 assistant    │
│ { "result": 999 }            │ final answer — word diff              │
└──────────────────────────────┴───────────────────────────────────────┘
```

## Why

Agent bugs are rarely reproducible: a flaky tool, a different sampling path,
and the failure is gone. The flight recorder makes agent execution
**append-only, deterministic, and forkable**:

- **Immutable event log** — steps are OpenTelemetry-style spans (trace id, span
  id, causal parent, timestamps, latency, token usage, cost). Nothing is ever
  updated in place.
- **Zero-copy forks** — a branch stores `parent_branch_id + fork_seq`; shared
  history is *inherited*, not duplicated. Forking is O(1) regardless of trace size.
- **Deterministic replay** — the first live result of every `(tool, args)` pair
  is cached per run; replays resolve from that cache, randomness is seeded, and
  temperature is 0. The only divergence in a fork is the thing you changed.
- **AI post-mortems** — each settled branch is labelled
  (`success / hallucination / loop / failed`) with a diagnosis of *why* it
  diverged; each settled run gets a summary.

## Quickstart (no API key needed)

The default `mock` provider is a deterministic, seeded agent brain — the whole
product works completely offline.

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

**Or Docker:**

```bash
docker compose up --build   # UI at http://localhost:3000
```

To use a real model, copy `.env.example` → `backend/.env` and set
`LLM_PROVIDER=openai` plus `OPENAI_API_KEY` (any OpenAI-compatible endpoint
works via `OPENAI_BASE_URL` — vLLM, Ollama, LM Studio…).

## Using it

1. **▶ New run** — give the agent a task. Example prompts exercise all four
   tools: `web_search`, `calculator`, `file_reader`, `weather`.
2. Watch events stream onto the timeline live (SSE). Scrub with **← →**, switch
   lanes with **↑ ↓**.
3. Select any step and press **F**:
   - edit the **prompt** → replays from the start with the new prompt;
   - select a **tool result** and edit its JSON → the fork keeps history up to
     that step but believes *your* output instead;
   - change nothing → a control replay (which, thanks to the cache, reproduces
     the original — proof the recorder is deterministic).
4. The fork streams into its own lane, forking visually from the exact step it
   diverged. The **Divergence** panel shows the AI verdict, an aligned step
   diff, and a word-level diff of the final answers.
5. **⇩ Export** downloads the full trace as JSON; `POST /api/runs/import`
   restores it.

## Architecture

```
frontend  React 18 · TypeScript · Vite · Zustand · Tailwind v4
   │  typed REST                       SSE stream
   ▼                                     ▼
backend   FastAPI ── agent engine ── LLM provider (openai-compatible | mock)
   │            │        └── tools: web_search · calculator · file_reader · weather
   │            └── recorder ──► immutable event log ──► SSE bus
   ▼
SQLite (SQLAlchemy 2.0) — runs · branches · events · tool_cache
```

### Event model

Every event: `id · run_id · branch_id · seq · parent_event_id · trace_id ·
span_id · type · name · ts · duration_ms · payload · tokens_in · tokens_out ·
cost_usd · meta`. Events form a causal chain (`parent_event_id`) inside a
branch; branches form a tree per run.

A branch's *effective history* = walk the ancestor chain, take each ancestor's
events below the child's `fork_seq`, then the branch's own events
(`backend/app/agent/replay.py`). The UI receives fully resolved timelines; the
database stores each event exactly once.

### Replay semantics

Forking at step *N* rebuilds the LLM conversation from the effective history
below *N* (applying prompt/tool-output overrides), then resumes the loop.
Tool calls hit the run-scoped cache first, so unedited calls return byte-equal
results. The mock provider derives its choices from
`seed + sha256(prompt)`, so even "the model" is reproducible; with a real
provider, determinism holds for tools and is best-effort for the LLM
(temperature 0 + `seed` param).

### Backend layout

```
backend/app/
├── main.py            FastAPI app, CORS, lifespan
├── config.py          pydantic-settings (all env vars)
├── db.py              engine/session, SQLite WAL
├── models.py          Run · Branch · Event · ToolCacheEntry
├── schemas.py         typed API contract (mirrored in src/api/types.ts)
├── events.py          event/status/label vocabulary
├── pricing.py         per-model $/token tables → cost per event
├── bus.py             asyncio pub/sub → SSE
├── agent/
│   ├── engine.py      plan→act→observe loop; records everything
│   ├── llm.py         OpenAICompatProvider · MockProvider
│   ├── recorder.py    append-only event writer + publisher
│   ├── replay.py      effective history · fork creation · branch diff
│   ├── cache.py       deterministic tool-output cache
│   └── tools/         calculator · web_search · file_reader · weather
├── analysis/
│   └── analyzer.py    branch labels · divergence diagnosis · run summary
└── api/
    ├── runs.py        CRUD + export/import
    ├── branches.py    timeline · fork · diff · re-analyze
    └── stream.py      SSE endpoint with heartbeats
```

### API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/runs` | start a run (agent executes in the background) |
| `GET` | `/api/runs` / `/api/runs/{id}` | list / detail |
| `DELETE` | `/api/runs/{id}` | delete a run and its branches |
| `GET` | `/api/runs/{id}/export` | full trace as JSON |
| `POST` | `/api/runs/import` | restore an exported trace |
| `GET` | `/api/branches/{id}/timeline` | resolved events + token/cost stats |
| `POST` | `/api/branches/{id}/fork` | fork at `fork_seq` with optional overrides |
| `GET` | `/api/branches/{id}/diff` | aligned diff vs parent (or `?against=`) |
| `POST` | `/api/branches/{id}/analyze` | re-run the AI post-mortem |
| `GET` | `/api/stream/runs/{id}` | SSE: `event` / `branch_update` / `run_update` |
| `GET` | `/api/health` | health + provider info |

Interactive docs at `http://localhost:8000/docs`.

## Keyboard

`← →` scrub · `↑ ↓` switch branch · `F` fork · `N` new run · `?` help ·
`Esc` close.

## Tests

```bash
cd backend && python -m pytest        # 17 tests
cd frontend && npm run build          # tsc --noEmit + production build
```

The suite covers calculator sandboxing, seeded tool determinism, full trace
capture with causal chaining, **byte-identical repeated runs**, fork
inheritance without copying, override propagation into diverged answers,
diff alignment, AI labelling, and export/import round-trips.

## Design notes

- **Why SSE over WebSockets** — the stream is strictly server→client;
  `EventSource` gives auto-reconnect for free, and a REST snapshot re-syncs
  state after a drop.
- **Why the mock search corpus** — live search would break replay determinism
  and require keys. The interface matches a real search API, so swapping one in
  is a one-file change; the tool cache would then pin its outputs anyway.
- **Immutability as an invariant** — the recorder only ever inserts; the tool
  cache is first-write-wins; forks reference, never copy.

## Roadmap

- Shareable permalinks (`/run/{id}/branch/{id}/step/{seq}` deep links)
- Regression replay suite (assert a forked fix stays fixed across seeds)
- Python SDK decorator (`@flight_recorder.trace`) to instrument external agents
- Flame-graph latency view of span durations

## License

MIT
