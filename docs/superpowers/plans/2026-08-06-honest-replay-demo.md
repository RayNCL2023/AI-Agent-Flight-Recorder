# Honest Replay Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor Agent Flight Recorder into a deployment-ready public demo that replays recorded agent executions, never fabricates AI output, and cleanly separates Replay Mode (default) from a key-gated Live Mode.

**Architecture:** Add an LLM-completion cache parallel to the existing tool cache; recorded trace bundles ship events + both caches + curated "experiments" (recorded fork variants). In Replay Mode the engine resolves every LLM/tool step from recorded material and emits an honest `replay_miss` event on any state with no recorded coverage. `MockProvider` is deleted. The frontend gains a landing page + trace library, a replay player (play/pause/scrub/speed), a persistent mode badge with popover, and a fork dialog built around recorded experiments.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · SQLite · pydantic v2 · React 18 · TypeScript · Vite · Zustand · Tailwind v4.

## Global Constraints

- Replay Mode is the default; badge copy exactly: `Replay Mode • Viewing recorded execution traces • Live AI disabled`.
- Live unavailable copy exactly: `Live execution unavailable.` plus BYOK instructions. Never silently downgrade live → replay.
- Honest failure copy exactly: `No recorded execution matches this request.`
- Hero copy exactly: `Time-travel debugging for AI agents.` / `Replay, inspect, fork and compare every decision an LLM agent makes.`
- Nothing shown in the UI may be generated at runtime by a fake model; all assistant/reasoning/tool content originates from stored recordings (or a real LLM in Live Mode).
- Only refactor what's needed; keep event-log/fork/diff/SSE machinery and visual identity.
- Gates: `cd backend && python -m pytest` green; `cd frontend && npm run build` green.

---

### Task 1: Baseline safety net

**Files:** none modified.

- [ ] `git init`, commit everything as baseline (excluding `.venv`, `node_modules`, `data/` via existing `.gitignore` — verify it covers them, extend if not).
- [ ] Run `python -m pytest` in backend, `npm run build` in frontend; record baseline status.

### Task 2: Vocabulary + config for modes

**Files:** `backend/app/events.py`, `backend/app/config.py`, `.env.example`

**Produces:**
- `EventType.REPLAY_MISS = "replay_miss"`, `BranchLabel.UNRECORDED = "unrecorded"`.
- `Settings.mode: Literal["replay","live"] = "replay"` (env `AFR_MODE`), replacing `llm_provider`. Keep `openai_*`/`llm_*` fields for Live Mode.
- `Settings.live_available -> bool` property: `mode == "live" and bool(openai_api_key)`.
- `.env.example` rewritten around `AFR_MODE` with BYOK notes.

### Task 3: LLM completion cache

**Files:** `backend/app/models.py` (add `LLMCacheEntry`), new `backend/app/agent/llm_cache.py`, `backend/app/db.py` (idempotent SQLite `ALTER TABLE` helper for new columns), `backend/tests/test_llm_cache.py`

**Produces:**
- `LLMCacheEntry`: id, run_id FK, cache_key (sha256, unique per run), response JSON, created_at.
- `llm_cache.cache_key(model: str, seed: int, messages: list[Message]) -> str` — sha256 over canonical JSON (`sort_keys`, compact separators, `default=str`).
- `llm_cache.lookup(db, run_id, key) -> dict | None`; `llm_cache.store(db, run_id, key, response: dict)` first-write-wins.
- Response dict shape: `{"content", "reasoning", "tool_calls": [{"id","name","arguments"}], "tokens_in", "tokens_out", "model", "duration_ms"}`.
- `Run` columns: `source: str = "live"` (`"recorded"` for library traces), `description: str | None`, `tools_used: JSON list`, `experiments: JSON list`. `Branch` column: `analysis_source: str = "heuristic"` (`"recorded" | "heuristic" | "llm"`).

TDD: key stability (same messages ⇒ same key; changed content ⇒ different), store/lookup round-trip, first-write-wins.

### Task 4: Delete MockProvider; honest engine

**Files:** `backend/app/agent/llm.py` (remove `MockProvider` + all `_plan_tool_calls`/`_synthesise_answer` helpers; keep `OpenAICompatProvider`, dataclasses, protocol), `backend/app/agent/engine.py`, `backend/app/agent/scripted.py` (new), `backend/tests/test_engine_replay.py`

**Interfaces:**
- `build_provider(settings) -> LLMProvider | None`: returns `OpenAICompatProvider` when `settings.live_available`, else `None` (replay). `model_name(settings)`: llm_model when live else `"recorded"`.
- `execute_branch(run_id, branch_id, messages, start_seq, parent_event_id, provider: LLMProvider | None = _UNSET)` — explicit provider injection for the recording harness/tests; default builds from settings.
- Engine loop per step: compute `key = cache_key(run.model, run.seed, messages)`; on cache hit, reconstruct `LLMResponse` from cached dict, use its stored `duration_ms`, record events with `meta={"replayed": True, ...}`. On miss with a provider: call it, `store()` result (including measured duration). On miss with no provider: record `REPLAY_MISS` event `{"message": "No recorded execution matches this request.", "context": "llm"}`, branch → FAILED, return.
- `_execute_tool` gains `live: bool`; on tool-cache miss when not live: record `REPLAY_MISS` (`"context": "tool"`) and raise `ReplayMiss` handled by the loop (branch fails honestly; no tool executes).
- `ScriptedProvider(turns)` in `scripted.py`: plays a fixed list of turns (`{"reasoning", "content" | "tool_calls", "latency_ms"}`), indexes by count of prior assistant messages, `asyncio.sleep(latency_ms/1000)` so recordings carry real timing. Docstring: used only by the recording harness and tests; never selectable at runtime.

TDD: scripted run records full trace + populates llm_cache; control-replay fork (no provider) reproduces payload-identical events from caches alone; unrecorded edit yields `replay_miss` + failed branch + zero fabricated content.

### Task 5: Schemas + API for library/modes

**Files:** `backend/app/schemas.py`, `backend/app/api/runs.py`, `backend/app/api/branches.py` (fork passes provider=None implicitly; no change beyond imports if engine handles it), `backend/app/main.py` (add `/api/meta`), `backend/tests/test_api_modes.py`

**Produces:**
- `ExperimentOut`: `{id, title, description, fork_seq, edited_prompt: str|None, tool_overrides: dict, recorded_label, recorded_diagnosis}`.
- `RunOut` += `description, source, tools_used`; `RunDetail` += `experiments: list[ExperimentOut]`; new `RunListItem(RunOut)` += `stats: {events, tokens, cost_usd, duration_ms}` (single aggregate SQL over events grouped by run).
- `BranchOut` += `analysis_source`.
- `RunExport` version 2 += `tool_cache: list[{cache_key,tool,args,output}]`, `llm_cache: list[{cache_key,response}]` (import accepts v1 with empty caches).
- `POST /api/runs`: 409 in replay mode (`detail` includes the honest copy + pointer to library); 409 in live mode without key (`Live execution unavailable.` + BYOK instructions). Only executes when `live_available`.
- `DELETE /api/runs/{id}`: 409 for `source == "recorded"`.
- `GET /api/meta`: `{mode, live_available, model, version}`.

### Task 6: Analyzer honesty

**Files:** `backend/app/analysis/analyzer.py`, tests in `backend/tests/test_api_modes.py`

- Branch containing `replay_miss` → label `UNRECORDED`, diagnosis states no recorded coverage + how to see recorded experiments; `analysis_source="heuristic"`.
- Branch whose `(fork_seq, overrides)` matches a run experiment → use `recorded_label`/`recorded_diagnosis`, `analysis_source="recorded"`.
- Live mode with key → LLM judge (existing `_llm_analysis`), `analysis_source="llm"`; otherwise heuristic, labeled as such. Remove any mock-provider analysis path.

### Task 7: Fixture corpus + recording harness + bundled traces

**Files:** `backend/app/agent/tools/web_search.py` (extend corpus for the five scenarios; add `"source": "offline_corpus"` to output), `backend/sample_data/server.log` (new), `backend/scripts/record_fixtures.py` (new), `backend/app/traces/*.json` (generated), `backend/app/seeds.py` (new), `backend/app/main.py` (seed on lifespan), `backend/app/pricing.py` (price entry for the scripted model), `backend/tests/test_library.py`

**Traces (5), each with 1–2 experiments:**
1. *Research a startup* — web_search ×2 → answer. Experiments: prompt variant (different company, fully recorded); empty-search override → recorded continuation that honestly reports lack of evidence.
2. *Compare two programming languages* — Python vs Rust, web_search ×2. Experiment: prompt variant Python vs Go.
3. *Investigate a bug* — bad `file_reader` path (error → retry → error), correct read of `server.log`, web_search for the error, answer. Experiment: log-content override → different recorded root-cause.
4. *Plan a trip* — weather + calculator + web_search. Experiment: storm weather override → recorded indoor plan.
5. *Summarise documentation* — file_reader `mission_report.md` → answer. Experiment: control replay (no overrides) as a determinism proof.

**Harness:** builds each trace by running `execute_branch` with `ScriptedProvider` against a temp DB, records experiments by running `create_fork` + variant scripts (populating llm_cache for variant paths), stamps `source="recorded"`, description, tools_used, experiments, then writes v2 export JSON into `app/traces/`. Run once; commit JSONs.

**Seeds:** `seeds.load_bundled_traces()` on startup imports any bundle whose run id is absent (idempotent).

TDD: library present after startup with stats; experiment fork replays to the recorded divergent answer + recorded diagnosis; determinism experiment reproduces original payloads; export/import v2 round-trips caches.

### Task 8: Rework legacy backend tests

**Files:** `backend/tests/conftest.py` (env `AFR_MODE=replay`, temp traces? point at real bundles), delete/replace `backend/tests/test_runs_and_forks.py` scenarios that depended on MockProvider free-text runs with fixture-driven equivalents; keep `test_tools.py` (adjust for corpus additions if asserted).

### Task 9: Frontend contract + store

**Files:** `frontend/src/api/types.ts`, `frontend/src/api/client.ts`, `frontend/src/store/useStore.ts`, `frontend/src/lib/format.ts`

**Produces:**
- Types: `"replay_miss"` EventType, `"unrecorded"` label, `analysis_source` on BranchOut, `description/source/tools_used` on RunOut, `RunListItem` with `stats`, `ExperimentOut`, `RunDetail.experiments`, `Meta {mode, live_available, model, version}`.
- Client: `getMeta()`, `listRuns(): RunListItem[]`.
- Store: `view: "home" | "trace"`, `meta: Meta | null`, `player: {playing: boolean, speed: 1|2|4}`, `loadMeta()`, `goHome()`, `openRun` → sets view "trace"; `setPlaying/cycleSpeed/stepTo`; remove auto-open-first-run (home is default). `createRun` only used by live dialog.
- format.ts: glyph `∅` + warn tint for `replay_miss`; label tint for `unrecorded`; `fmtDuration`.

### Task 10: Landing page + trace library (invoke frontend-design skill first)

**Files:** `frontend/src/components/Home.tsx` (new: hero + animated trace background + library grid + live card), `frontend/src/App.tsx`, `frontend/index.html` (title/meta)

- Hero exact copy per Global Constraints; decorative animated SVG timeline background (CSS keyframes, `aria-hidden`, reduced-motion safe).
- Trace cards: title, description, tool chips, stats (duration, tokens, cost, events), `▶ Replay` → `openRun`.
- Live Mode section: when unavailable → exact copy + BYOK instructions (env vars, restart); when available → open live run dialog. Never renders a free-text box in Replay Mode.

### Task 11: Mode badge + top bar

**Files:** `frontend/src/components/ModeBadge.tsx` (new), `frontend/src/components/TopBar.tsx`

- Persistent badge: exact copy; popover explains recorded traces, determinism, zero API cost, exact reproducibility, forks-as-deterministic-branches. Live mode shows `Live Mode • model` variant.
- TopBar: `⌂ Library` nav, badge, keep export; delete-run button only for non-recorded runs; remove `▶ New run` (moves to Home live card).

### Task 12: Replay player

**Files:** `frontend/src/components/PlayerBar.tsx` (new), `frontend/src/hooks/usePlayback.ts` (new), `frontend/src/components/Timeline.tsx` (mount PlayerBar), `frontend/src/hooks/useKeyboard.ts` (Space toggles, existing arrows scrub)

- Playback advances selection along the selected branch using original `ts` deltas ÷ speed, clamped to [150ms, 2500ms]; stops at end; scrub slider (range input over event index); jump-to-event = existing node click; pause/resume; speed 1×/2×/4×.

### Task 13: Fork dialog around recorded experiments

**Files:** `frontend/src/components/ForkDialog.tsx`

- Section 1 "Recorded experiments": cards from `run.experiments` (title, description, what changes); click → fork with the experiment's exact `fork_seq`/overrides.
- Section 2 "Custom modification": existing prompt/tool-output editors plus an honesty note: custom changes replay only recorded coverage and otherwise stop with `No recorded execution matches this request.` (In Live Mode the note switches to live-execution wording.)

### Task 14: Honest failure surfaces

**Files:** `frontend/src/components/Inspector.tsx` (render `replay_miss` events: exact copy, context, suggested experiments), `frontend/src/components/DiffPanel.tsx` (verdict shows `analysis_source` tag: recorded post-mortem / heuristic analysis / LLM judge), `frontend/src/components/HelpOverlay.tsx` (Space key, library nav), `frontend/src/components/RunLauncher.tsx` → repurpose as `LiveRunDialog` reachable only when `meta.live_available`.

### Task 15: README + ops + final gates

**Files:** `README.md` (rewrite: value prop, replay model, event schema, deterministic replay strategy incl. LLM cache, honest-failure design, trace provenance — bundled traces are curated recordings produced by the scripted harness, regenerable via `scripts/record_fixtures.py`; limitations; future Live Mode/BYOK; why replay beats a fake live demo; trade-offs), `docker-compose.yml` check, `.env.example` final.

- [ ] Full gates: backend pytest green, frontend `npm run build` green.
- [ ] Self-review against the spec section by section.

## Self-Review Notes

- Spec "Remove Fake Chat Behaviour" → Tasks 4 (MockProvider deleted), 7 (recorded traces replace it).
- Spec "Replace Free Chat" → Tasks 10, 14 (cards; free text only in Live Mode).
- Spec "Honest Failure States" → Tasks 4, 6, 14.
- Spec "Trace Library" → Tasks 5, 7, 10.
- Spec "Replay UX" → Task 12 (+ existing inspector for reasoning/tools/latency/tokens/cost).
- Spec "Forking" → Tasks 4, 6, 7, 13 (immutable branches, diverging lanes, diffs, diagnosis already exist).
- Spec "Explainability" → existing Inspector/raw event JSON + Task 14 labels.
- Spec "Architecture" (immutable log, cached tool outputs, seeded randomness, versioned prompts/models, stable IDs) → existing + Task 3.
- Spec "Landing Page" → Task 10. "README" → Task 15. "Code Quality" → throughout; gates in Task 15.
