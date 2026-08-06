# Agent Flight Recorder — Design

**Date:** 2026-07-29
**Status:** Approved (built from user-provided full specification; open decisions resolved below)

## 1. Concept

A time-travel debugger for LLM agents. Every execution step (LLM message, reasoning,
tool call, tool result, retry, error, completion) is an **immutable event** on a
**branching timeline**. Users scrub to any step, edit the prompt or mock a tool
response, click **Fork**, and replay execution from that point. The replay becomes a
new branch alongside the original so behavioural divergence is immediately visible.

## 2. Resolved decisions

| Decision | Choice | Why |
|---|---|---|
| Streaming transport | **SSE** | One-directional stream; simpler than WS; native `EventSource` reconnect |
| LLM provider | **OpenAI-compatible + built-in deterministic mock** | Runs with zero API keys for demos; real provider via env vars |
| Fork storage | **Zero-copy: branch = `parent_branch_id` + `fork_seq`** | Immutable log, O(1) forks, no event duplication |
| Determinism | **Tool-output cache (keyed by tool+args hash) + seeded RNG + temperature 0** | Replays reproduce the original unless the user changes something |
| 4th tool | **Mock weather API** | Fully deterministic, seeded |
| Bonus scope | **Export/import shipped; SDK / flame graph / permalinks = roadmap** | YAGNI |

## 3. Architecture

```
frontend (React 18 + TS + Vite + Zustand + Tailwind)
   │  REST (typed JSON)            SSE (event stream)
   ▼                                ▼
backend (FastAPI) ── agent engine ── LLM provider (openai-compat | mock)
   │                    │   └─ tools: web_search, calculator, file_reader, weather
   │                    └─ recorder → immutable event log
   ▼
SQLite (SQLAlchemy 2.0): runs / branches / events / tool_cache
```

### Backend modules (`backend/app/`)

- `config.py` — pydantic-settings, all env vars.
- `db.py` — SQLAlchemy engine/session, SQLite WAL.
- `models.py` — ORM: `Run`, `Branch`, `Event`, `ToolCacheEntry`.
- `schemas.py` — Pydantic v2 API schemas (typed, mirrored in TS).
- `events.py` — event-type enum + OTel-inspired span payloads.
- `pricing.py` — per-model token pricing table → cost per event.
- `agent/engine.py` — the agent loop (plan → tool call → observe → answer).
- `agent/llm.py` — provider abstraction: `OpenAICompatProvider`, `MockProvider`.
- `agent/tools/` — 4 tools behind one registry, each returns `(output, meta)`.
- `agent/recorder.py` — writes immutable events + publishes to SSE bus.
- `agent/replay.py` — fork resolution: effective history, overrides, re-execution.
- `analysis/` — LLM branch labelling (Success/Hallucination/Loop/Failed),
  divergence diagnosis, run summary; heuristic fallback when no LLM.
- `api/` — routers: runs, branches, fork/replay, stream (SSE), analysis, export.
- `bus.py` — in-process asyncio pub/sub feeding SSE subscribers.

### Data model

- **Run**: id, title, prompt, model, seed, status, created_at.
- **Branch**: id, run_id, name, parent_branch_id, fork_seq, overrides(JSON),
  status, label, diagnosis, color_index. Root branch has no parent.
- **Event** (append-only, never mutated): id, run_id, branch_id, seq,
  parent_event_id, trace_id, span_id, type, name, ts, duration_ms,
  payload(JSON), tokens_in, tokens_out, cost_usd, meta(JSON).
- **ToolCacheEntry**: run_id, cache_key = sha256(tool, canonical-args), output(JSON).

**Effective history** of a branch = walk ancestor chain, take each ancestor's
events with `seq < child.fork_seq`, then own events. Single recursive resolve,
branch depth is small.

### Fork/replay flow

1. User selects event at `seq` on branch B, optionally edits the prompt and/or
   supplies replacement tool outputs (stored in `Branch.overrides`).
2. `POST /api/branches/{id}/fork` → new branch B′ (parent=B, fork_seq=seq).
3. Engine reconstructs conversation state from effective history < fork point,
   applies overrides, resumes the loop. Tool calls hit the cache first
   (deterministic); overridden outputs win over cache.
4. Events stream over SSE; frontend renders B′ as a new lane forking from seq.

## 4. Frontend

Terminal-inspired (dark, mono, scanline-subtle) three-panel layout:

1. **Timeline** (top, full width): horizontal lanes per branch, SVG fork
   connectors, event nodes coloured by type, playhead scrubbing, animated
   streaming nodes.
2. **Inspector** (left/bottom): selected event detail — payload, tokens,
   latency, cost; edit affordances (prompt / tool output) that arm a fork.
3. **Diff** (right): branch vs its parent — aligned event list with
   added/changed markers + word-level text diff of final answers.

Cross-cutting: per-branch token/cost meter, keyboard shortcuts
(←/→ scrub, ↑/↓ branch, F fork, E edit, R replay, ? help), typewriter
streaming, Zustand stores (`runs`, `timeline`, `ui`), typed API client
mirroring backend schemas, SSE hook with auto-reconnect.

## 5. Error handling

- Tool errors recorded as `error` events; engine retries once (recorded as
  `retry`) then surfaces failure; run status → `failed`.
- LLM provider errors → `error` event + run `failed`; UI shows the event.
- SSE drops → EventSource reconnects; client re-syncs via REST snapshot.
- Fork of a mid-stream branch is blocked until the branch settles.

## 6. Testing

Backend pytest: calculator safety, tool cache determinism, fork effective-history
resolution, replay divergence with an override, API smoke via `TestClient`
(mock provider, seeded). Frontend: `tsc --noEmit` + production build as the gate.

## 7. Ops

- `.env.example` documents every variable; mock mode is the default.
- Dockerfiles for backend (uvicorn) and frontend (nginx serving static + proxying
  `/api`), composed via `docker-compose.yml`.
- README: quickstart (local + Docker), architecture diagram, API table, shortcuts.
