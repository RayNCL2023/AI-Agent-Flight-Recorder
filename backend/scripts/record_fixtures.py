#!/usr/bin/env python
"""Recording harness for the bundled trace library.

Runs the *real* engine (real recorder, real tools, real caches) over curated
scripts, records each experiment variant so its LLM completions land in the
run's replay cache, verifies that every experiment then replays end-to-end with
NO provider (the production Replay Mode path), and writes v2 bundles to
`app/traces/`.

Usage (from backend/, venv active):
    python scripts/record_fixtures.py

The bundles are committed to the repository; re-run this script only when the
library content changes. Point the script at a live provider instead of
ScriptedProvider to record traces from a real model — the output format and
replay guarantees are identical.
"""

import asyncio
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="afr-record-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'record.db').as_posix()}"
os.environ["AFR_MODE"] = "replay"
os.environ["FILE_READER_ROOT"] = str(BACKEND / "sample_data")

from app.agent.engine import execute_branch  # noqa: E402
from app.agent.replay import create_fork, effective_events, initial_messages  # noqa: E402
from app.agent.scripted import SCRIPTED_MODEL, ScriptedProvider, Turn  # noqa: E402
from app.api.runs import export_run  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.events import BranchStatus, EventType, RunStatus  # noqa: E402
from app.models import Branch, Run  # noqa: E402
from app.schemas import ForkRequest  # noqa: E402

TRACES_DIR = BACKEND / "app" / "traces"


@dataclass(frozen=True)
class ExperimentSpec:
    id: str
    title: str
    description: str
    recorded_label: str
    recorded_diagnosis: str
    script: list[Turn]
    edited_prompt: str | None = None
    # Given the root branch's events, return (fork_seq, tool_overrides).
    locate: Callable[[list], tuple[int, dict]] = lambda events: (1, {})


@dataclass(frozen=True)
class TraceSpec:
    slug: str
    title: str
    description: str
    prompt: str
    seed: int
    summary: str
    script: list[Turn]
    experiments: list[ExperimentSpec] = field(default_factory=list)


def _at_start(_events: list) -> tuple[int, dict]:
    return 1, {}


def _override_tool_result(tool: str, nth: int, replacement: dict) -> Callable:
    """Fork right after the nth successful `tool` result, replacing its output."""

    def locate(events: list) -> tuple[int, dict]:
        seen = 0
        for ev in events:
            if ev.type == EventType.TOOL_RESULT and ev.payload.get("tool") == tool:
                out = ev.payload.get("output") or {}
                if "error" in out:
                    continue
                seen += 1
                if seen == nth:
                    return ev.seq + 1, {ev.id: replacement}
        raise LookupError(f"no {tool} result #{nth} in recorded events")

    return locate


# --------------------------------------------------------------------- content

DISK_FULL_LOG = """2026-08-05 01:58:12 INFO  deploy: starting release v2.14.0
2026-08-05 02:00:03 INFO  api: worker pool resized 4 -> 16
2026-08-05 02:01:07 ERROR db: sqlite3.OperationalError: disk I/O error (endpoint=/api/orders)
2026-08-05 02:01:22 ERROR db: database or disk is full (endpoint=/api/orders)
2026-08-05 02:02:05 WARN  storage: volume /data at 100% capacity
2026-08-05 02:03:40 ERROR db: database or disk is full (endpoint=/api/users)
"""

STORM_WEATHER = {
    "city": "Tokyo",
    "temperature_c": 8.4,
    "condition": "thunderstorms",
    "humidity_pct": 88,
    "wind_kph": 41.0,
    "source": "mock-weather-api",
}

_RESEARCH_TURNS = [
    Turn(
        reasoning=(
            "The prompt asks for company facts — product, founders, funding — that "
            "I should ground in sources rather than answer from memory. Starting "
            "with an overview search."
        ),
        tool_calls=[{"name": "web_search", "arguments": {"query": "Anthropic AI startup company"}}],
        latency_ms=780,
    ),
    Turn(
        reasoning=(
            "The overview covers product and founders. Funding needs its own "
            "search before I can answer that part."
        ),
        tool_calls=[{"name": "web_search", "arguments": {"query": "Anthropic funding investors billion"}}],
        latency_ms=910,
    ),
    Turn(
        reasoning="Both halves of the question are grounded in search results — composing the final answer.",
        content=(
            "Anthropic is an AI safety company founded in 2021 by Dario Amodei and "
            "Daniela Amodei. It develops the Claude family of large language models, "
            "focused on reliable, interpretable and steerable AI systems.\n\n"
            "On funding: Anthropic has raised over $7 billion in total, including a "
            "2023 agreement with Amazon worth up to $4 billion and investment from "
            "Google (per the funding overview source)."
        ),
        latency_ms=1420,
    ),
]

TRACES = [
    TraceSpec(
        slug="research-startup",
        title="Research a startup",
        description=(
            "A grounded research run: overview search, funding search, sourced "
            "answer. Its experiments swap the research target and erase the "
            "funding evidence."
        ),
        prompt=(
            "Research the AI startup Anthropic: what does the company build, "
            "who founded it, and how much funding has it raised?"
        ),
        seed=11,
        summary=(
            "Two web searches ground a company profile of Anthropic — product, "
            "founders, funding — with every claim traceable to a search result."
        ),
        script=_RESEARCH_TURNS,
        experiments=[
            ExperimentSpec(
                id="research-mistral",
                title="Change the research target",
                description="Edit the prompt to research Mistral AI instead and replay from the start.",
                edited_prompt=(
                    "Research the AI startup Mistral AI: what does the company build, "
                    "who founded it, and how much funding has it raised?"
                ),
                locate=_at_start,
                recorded_label="success",
                recorded_diagnosis=(
                    "The edited prompt changed the research target, so the fork planned a "
                    "different search from the very first step. Every downstream fact — "
                    "founders, product, funding — now grounds in the Mistral documents "
                    "instead of the Anthropic ones; both branches remain fully source-grounded."
                ),
                script=[
                    Turn(
                        reasoning=(
                            "The target is Mistral AI; one search should cover product, "
                            "founders and funding for a company this young."
                        ),
                        tool_calls=[{"name": "web_search", "arguments": {"query": "Mistral AI startup funding"}}],
                        latency_ms=800,
                    ),
                    Turn(
                        reasoning="The overview result covers both product and funding — answering.",
                        content=(
                            "Mistral AI is a French AI startup founded in 2023 by former "
                            "DeepMind and Meta researchers. It builds open-weight large "
                            "language models, and raised €600 million in 2024 at a valuation "
                            "near €6 billion (per the company overview source)."
                        ),
                        latency_ms=1180,
                    ),
                ],
            ),
            ExperimentSpec(
                id="research-empty-search",
                title="Erase the funding evidence",
                description=(
                    "Replace the funding search result with zero results and watch the "
                    "recorded agent decline to invent a figure."
                ),
                locate=_override_tool_result(
                    "web_search",
                    2,
                    {
                        "query": "Anthropic funding investors billion",
                        "results": [],
                        "total": 0,
                        "source": "offline_corpus",
                    },
                ),
                recorded_label="success",
                recorded_diagnosis=(
                    "The overridden tool output erased the funding evidence. Instead of "
                    "hallucinating a number, the recorded agent explicitly declined to "
                    "answer that part of the question — compare the final answers to see "
                    "the funding claim disappear while the grounded overview survives."
                ),
                script=[
                    _RESEARCH_TURNS[0],
                    _RESEARCH_TURNS[1],
                    Turn(
                        reasoning=(
                            "The funding search returned zero results. I have no evidence "
                            "for any funding figure, and I won't invent one."
                        ),
                        content=(
                            "Anthropic is an AI safety company founded in 2021 by Dario "
                            "Amodei and Daniela Amodei, known for the Claude family of "
                            "large language models.\n\nHowever, the funding search returned "
                            "no results, so I cannot verify how much the company has "
                            "raised — that part of the question remains unanswered rather "
                            "than guessed."
                        ),
                        latency_ms=1350,
                    ),
                ],
            ),
        ],
    ),
    TraceSpec(
        slug="compare-languages",
        title="Compare two programming languages",
        description=(
            "Python vs Rust for a high-throughput API server, argued from tool "
            "evidence. The experiment swaps Rust for Go and replays the debate."
        ),
        prompt=(
            "Compare Python and Rust for building a high-throughput API server. "
            "Which would you pick and why?"
        ),
        seed=23,
        summary=(
            "Evidence-gathering on both languages feeds a throughput-vs-velocity "
            "recommendation; the Go experiment shows the comparison axis pivoting "
            "with a one-word prompt edit."
        ),
        script=[
            Turn(
                reasoning="Two candidates to compare; gathering evidence on Rust's server story first.",
                tool_calls=[{"name": "web_search", "arguments": {"query": "Rust language memory safety high-throughput server"}}],
                latency_ms=730,
            ),
            Turn(
                reasoning="Now the Python side, specifically async throughput characteristics.",
                tool_calls=[{"name": "web_search", "arguments": {"query": "Python asyncio API throughput GIL"}}],
                latency_ms=690,
            ),
            Turn(
                reasoning="Evidence on both sides — weighing raw throughput against developer velocity.",
                content=(
                    "For a high-throughput API server, **Rust** is the stronger pick on raw "
                    "performance: memory safety without garbage collection, and an async "
                    "ecosystem (Tokio, hyper) built for very high-throughput network "
                    "services. **Python** with asyncio and FastAPI handles I/O-bound "
                    "workloads well and wins on developer velocity and ecosystem, but the "
                    "GIL limits CPU-bound parallelism and raw throughput trails compiled "
                    "languages.\n\nPick Rust when throughput is the hard requirement; pick "
                    "Python when iteration speed matters more than the last order of magnitude."
                ),
                latency_ms=1650,
            ),
        ],
        experiments=[
            ExperimentSpec(
                id="compare-go",
                title="Swap Rust for Go",
                description="Edit the prompt to compare Python with Go instead and replay.",
                edited_prompt=(
                    "Compare Python and Go for building a high-throughput API server. "
                    "Which would you pick and why?"
                ),
                locate=_at_start,
                recorded_label="success",
                recorded_diagnosis=(
                    "Swapping Rust for Go changed the first search and the whole comparison "
                    "axis: the fork's recommendation leans on Go's goroutines and single-binary "
                    "deployment story rather than Rust's zero-cost memory safety. The Python "
                    "evidence step is identical in both branches — same query, and the result "
                    "replays from the run's tool cache."
                ),
                script=[
                    Turn(
                        reasoning="The candidates are Python and Go; gathering Go's concurrency evidence first.",
                        tool_calls=[{"name": "web_search", "arguments": {"query": "Go language concurrent servers goroutines"}}],
                        latency_ms=700,
                    ),
                    Turn(
                        reasoning="Now the Python side, same throughput question as any comparison.",
                        tool_calls=[{"name": "web_search", "arguments": {"query": "Python asyncio API throughput GIL"}}],
                        latency_ms=680,
                    ),
                    Turn(
                        reasoning="Evidence on both sides — weighing operational simplicity against ecosystem.",
                        content=(
                            "For a high-throughput API server, **Go** is the pragmatic pick: "
                            "goroutines and channels make concurrent servers simple, it "
                            "compiles fast, and it deploys as a single static binary. "
                            "**Python** with asyncio handles I/O-bound APIs well and offers "
                            "unmatched ecosystem velocity, but the GIL constrains CPU-bound "
                            "parallelism.\n\nChoose Go for sustained throughput with simple "
                            "operations; choose Python when developer speed dominates."
                        ),
                        latency_ms=1500,
                    ),
                ],
            ),
        ],
    ),
    TraceSpec(
        slug="investigate-bug",
        title="Investigate a bug",
        description=(
            "A real debugging arc: a wrong file path fails and retries, the log "
            "reveals lock contention, a doc search confirms the fix. The "
            "experiment rewrites the evidence into a different root cause."
        ),
        prompt=(
            "Our API started throwing 'database is locked' errors right after the "
            "02:00 deploy. Read server.log and figure out what went wrong."
        ),
        seed=31,
        summary=(
            "The investigation survives a failed file read, pins the lock errors to "
            "a long-running analytics write transaction amplified by a worker-pool "
            "resize, and confirms the WAL + busy_timeout fix against SQLite docs."
        ),
        script=[
            Turn(
                reasoning="First, the evidence: read the server log covering the deploy window.",
                tool_calls=[{"name": "file_reader", "arguments": {"path": "logs/server.log"}}],
                latency_ms=620,
            ),
            Turn(
                reasoning=(
                    "The path was wrong — the sandbox lists server.log at its root. "
                    "Retrying with the correct path."
                ),
                tool_calls=[{"name": "file_reader", "arguments": {"path": "server.log"}}],
                latency_ms=640,
            ),
            Turn(
                reasoning=(
                    "The log shows lock errors starting seconds after a full-table-scan "
                    "batch job began, on a freshly enlarged worker pool. Checking the "
                    "standard causes of SQLITE_BUSY to confirm before diagnosing."
                ),
                tool_calls=[{"name": "web_search", "arguments": {"query": "sqlite database is locked write transaction fix"}}],
                latency_ms=800,
            ),
            Turn(
                reasoning="Log evidence and documentation agree — writing the diagnosis.",
                content=(
                    "**Root cause:** at 02:00:41 the nightly analytics batch opened a long "
                    "full-table-scan write transaction, and the deploy had just resized the "
                    "worker pool from 4 to 16 — so sixteen workers piled up behind a single "
                    "write lock. The log's `journal_mode=DELETE busy_timeout=0` line confirms "
                    "the database runs in rollback-journal mode, where one long write blocks "
                    "every other writer; this matches the SQLITE_BUSY guidance found.\n\n"
                    "**Fix:** enable WAL journal mode and set a busy_timeout, and move the "
                    "analytics scan off the API database (or out of deploy windows). The "
                    "deploy itself only amplified the contention — it did not cause it."
                ),
                latency_ms=1900,
            ),
        ],
        experiments=[
            ExperimentSpec(
                id="bug-disk-full",
                title="Rewrite the log evidence",
                description=(
                    "Replace the log content with a disk-exhaustion incident and watch "
                    "the diagnosis — and the tool plan — change."
                ),
                locate=lambda events: _override_tool_result(
                    "file_reader",
                    1,
                    {
                        "path": "server.log",
                        "size_bytes": len(DISK_FULL_LOG.encode()),
                        "content": DISK_FULL_LOG,
                    },
                )(events),
                recorded_label="success",
                recorded_diagnosis=(
                    "With the log evidence swapped, the same investigation reaches a "
                    "different verdict: storage exhaustion instead of lock contention. The "
                    "fork also skips the SQLite-locking search — the rewritten evidence made "
                    "that step unnecessary — so the branches diverge in both their tool plan "
                    "and their final diagnosis."
                ),
                script=[
                    Turn(
                        reasoning="unused — inherited history covers this step",
                        tool_calls=[{"name": "file_reader", "arguments": {"path": "logs/server.log"}}],
                        latency_ms=1,
                    ),
                    Turn(
                        reasoning="unused — inherited history covers this step",
                        tool_calls=[{"name": "file_reader", "arguments": {"path": "server.log"}}],
                        latency_ms=1,
                    ),
                    Turn(
                        reasoning=(
                            "This log shows no lock contention at all — it is storage "
                            "exhaustion. The planned locking search is unnecessary now; "
                            "the evidence is already sufficient."
                        ),
                        content=(
                            "**Root cause:** the /data volume hit 100% capacity at 02:02, so "
                            "SQLite began failing with 'database or disk is full' — the timing "
                            "next to the deploy is coincidental, and the worker-pool resize "
                            "only amplified the error rate.\n\n**Fix:** free or grow the /data "
                            "volume, add disk-usage alerting, and cap whatever filled it. No "
                            "locking or journal-mode change is needed."
                        ),
                        latency_ms=1600,
                    ),
                ],
            ),
        ],
    ),
    TraceSpec(
        slug="plan-trip",
        title="Plan a trip",
        description=(
            "Weather, budget arithmetic and an attractions search feed a 3-day "
            "Tokyo itinerary. The experiment storms the forecast and only the "
            "itinerary responds."
        ),
        prompt=(
            "Plan a 3-day Tokyo trip for mid-November: check the weather, estimate "
            "the budget at $180/day plus a $950 flight, and suggest what to see."
        ),
        seed=4,
        summary=(
            "Three tools — weather, calculator, search — compose an itinerary whose "
            "outdoor/indoor balance is decided by the forecast; the budget is pure "
            "arithmetic and replays identically in every fork."
        ),
        script=[
            Turn(
                reasoning="Weather first — it decides whether this is an outdoor or indoor itinerary.",
                tool_calls=[{"name": "weather", "arguments": {"city": "Tokyo"}}],
                latency_ms=560,
            ),
            Turn(
                reasoning="Now the arithmetic: three days at $180 plus the flight.",
                tool_calls=[{"name": "calculator", "arguments": {"expression": "180*3+950"}}],
                latency_ms=480,
            ),
            Turn(
                reasoning="Finally, what is actually worth seeing in November.",
                tool_calls=[{"name": "web_search", "arguments": {"query": "Tokyo attractions November autumn"}}],
                latency_ms=820,
            ),
            Turn(
                reasoning="Forecast is clear, budget is fixed, sights are sourced — assembling the plan.",
                content=(
                    "**3-day Tokyo plan for mid-November**\n\n"
                    "**Weather** — clear, around 10.7°C with 15 kph wind (68% humidity): "
                    "pack layers, but outdoor days are on.\n\n"
                    "**Budget** — 180×3 + 950 flight = **$1,490** total.\n\n"
                    "**Itinerary** — Day 1: Senso-ji temple and Asakusa, evening at Shibuya "
                    "crossing. Day 2: Meiji Shrine plus autumn-foliage walks (November is "
                    "peak). Day 3: teamLab Planets, with a Mount Takao day trip as the "
                    "clear-weather option."
                ),
                latency_ms=2100,
            ),
        ],
        experiments=[
            ExperimentSpec(
                id="trip-storm",
                title="Storm the forecast",
                description=(
                    "Override the weather with thunderstorms and watch the itinerary go "
                    "indoors while the budget replays untouched."
                ),
                locate=_override_tool_result("weather", 1, STORM_WEATHER),
                recorded_label="success",
                recorded_diagnosis=(
                    "Only the weather evidence changed, and only the itinerary responds: the "
                    "budget arithmetic replays byte-identically from the tool cache while the "
                    "recommendation flips from outdoor-first to indoor-first. A clean "
                    "single-input counterfactual."
                ),
                script=[
                    Turn(
                        reasoning="unused — inherited history covers this step",
                        tool_calls=[{"name": "weather", "arguments": {"city": "Tokyo"}}],
                        latency_ms=1,
                    ),
                    Turn(
                        reasoning="Thunderstorms change everything about the itinerary — but the budget math is unchanged.",
                        tool_calls=[{"name": "calculator", "arguments": {"expression": "180*3+950"}}],
                        latency_ms=500,
                    ),
                    Turn(
                        reasoning="Same sights question — the answer just has to filter for covered venues now.",
                        tool_calls=[{"name": "web_search", "arguments": {"query": "Tokyo attractions November autumn"}}],
                        latency_ms=780,
                    ),
                    Turn(
                        reasoning="Storm forecast, fixed budget, sourced sights — assembling an indoor-first plan.",
                        content=(
                            "**Storm-proofed 3-day Tokyo plan for mid-November**\n\n"
                            "**Weather** — thunderstorms, 8.4°C, 41 kph wind: this is an "
                            "indoor itinerary.\n\n"
                            "**Budget** — unchanged at **$1,490** (180×3 + 950).\n\n"
                            "**Itinerary** — Day 1: teamLab Planets, then the covered Asakusa "
                            "arcades beside Senso-ji. Day 2: museums and department-store food "
                            "halls; keep Meiji Shrine's open grounds for a gap between cells. "
                            "Day 3: Shibuya's indoor observation decks for the crossing view — "
                            "and drop the Mount Takao trip; exposed ridgelines and lightning "
                            "don't mix."
                        ),
                        latency_ms=1950,
                    ),
                ],
            ),
        ],
    ),
    TraceSpec(
        slug="summarise-docs",
        title="Summarise documentation",
        description=(
            "The simplest trace: read a report, summarise it faithfully. Its "
            "experiment is a control replay — the determinism proof for the whole "
            "library."
        ),
        prompt="Read mission_report.md and summarise the key findings and open risks for the team.",
        seed=52,
        summary=(
            "A single file read feeds a faithful summary; the control-replay "
            "experiment demonstrates that an unmodified fork reproduces the "
            "recording event-for-event."
        ),
        script=[
            Turn(
                reasoning="Read the document before summarising anything.",
                tool_calls=[{"name": "file_reader", "arguments": {"path": "mission_report.md"}}],
                latency_ms=610,
            ),
            Turn(
                reasoning="The report is short and complete — summarising findings, then flagging risks.",
                content=(
                    "**Summary of Mission Report — Q3 Orbital Survey**: the survey is "
                    "complete — 14 days, 1,240 orbital passes, 82.4 TB captured, downlink "
                    "efficiency averaging 97.2%. Two anomalies occurred and both are "
                    "resolved; sensor drift was corrected on day 6.\n\n**Open risks:** none "
                    "are flagged in the report itself, but the day-6 sensor-drift correction "
                    "deserves a follow-up calibration check before the next survey window."
                ),
                latency_ms=1500,
            ),
        ],
        experiments=[
            ExperimentSpec(
                id="docs-control-replay",
                title="Control replay (determinism proof)",
                description=(
                    "Fork with no changes at all. The replay must reproduce the original "
                    "event-for-event — proof that any divergence you see elsewhere was "
                    "caused by your edit."
                ),
                locate=_at_start,
                recorded_label="success",
                recorded_diagnosis=(
                    "A control replay: nothing was edited, and the fork reproduced the "
                    "original event-for-event from the recorded caches. This is the "
                    "determinism guarantee that makes every other experiment trustworthy — "
                    "any difference you ever see in a fork traces back to the thing you changed."
                ),
                script=[],
            ),
        ],
    ),
]


# ------------------------------------------------------------------- recording


def _run_engine(run_id: str, branch_id: str, messages, start_seq: int, parent_event_id, provider) -> None:
    asyncio.run(
        execute_branch(run_id, branch_id, messages, start_seq, parent_event_id, provider=provider)
    )


def _final_answer(events) -> str | None:
    for ev in reversed(events):
        if ev.type == EventType.COMPLETION:
            return ev.payload.get("content")
    return None


def record_trace(spec: TraceSpec) -> dict:
    db = SessionLocal()
    try:
        run = Run(
            title=spec.title,
            prompt=spec.prompt,
            model=SCRIPTED_MODEL,
            seed=spec.seed,
            source="recorded",
            description=spec.description,
        )
        root = Branch(name="main", status=BranchStatus.PENDING, color_index=0)
        run.branches.append(root)
        db.add(run)
        db.commit()
        run_id, root_id = run.id, root.id
    finally:
        db.close()

    _run_engine(run_id, root_id, initial_messages(spec.prompt), 1, None, ScriptedProvider(spec.script))

    db = SessionLocal()
    try:
        run = db.get(Run, run_id)
        root = db.get(Branch, root_id)
        assert root.status == BranchStatus.COMPLETED, f"{spec.slug}: root branch failed"
        events = effective_events(db, root)
        base_answer = _final_answer(events)

        experiments = []
        for exp in spec.experiments:
            fork_seq, tool_overrides = exp.locate(events)
            experiments.append(
                {
                    "id": exp.id,
                    "title": exp.title,
                    "description": exp.description,
                    "fork_seq": fork_seq,
                    "edited_prompt": exp.edited_prompt,
                    "tool_overrides": tool_overrides,
                    "recorded_label": exp.recorded_label,
                    "recorded_diagnosis": exp.recorded_diagnosis,
                }
            )
            # Record the variant so its completions land in the run's LLM cache.
            fork, messages, parent_event_id = create_fork(
                db, run, root,
                ForkRequest(
                    fork_seq=fork_seq,
                    name=f"rec-{exp.id}",
                    edited_prompt=exp.edited_prompt,
                    tool_overrides=tool_overrides,
                ),
            )
            fork_id = fork.id
            db.expire_all()
            _run_engine(run_id, fork_id, messages, fork_seq, parent_event_id, ScriptedProvider(exp.script))
            fork = db.get(Branch, fork_id)
            db.refresh(fork)
            assert fork.status == BranchStatus.COMPLETED, f"{spec.slug}/{exp.id}: variant failed"
            db.delete(fork)  # keep only the caches; users create the fork live
            db.commit()

        # Verify: every experiment must now replay end-to-end with NO provider,
        # through the exact code path Replay Mode uses in production.
        for exp_meta, exp in zip(experiments, spec.experiments):
            fork, messages, parent_event_id = create_fork(
                db, run, root,
                ForkRequest(
                    fork_seq=exp_meta["fork_seq"],
                    name=f"verify-{exp.id}",
                    edited_prompt=exp_meta["edited_prompt"],
                    tool_overrides=exp_meta["tool_overrides"],
                ),
            )
            fork_id = fork.id
            _run_engine(run_id, fork_id, messages, exp_meta["fork_seq"], parent_event_id, None)
            fork = db.get(Branch, fork_id)
            db.refresh(fork)
            assert fork.status == BranchStatus.COMPLETED, f"{spec.slug}/{exp.id}: replay verification failed"
            verify_answer = _final_answer(effective_events(db, fork))
            if exp.script:
                assert verify_answer != base_answer, f"{spec.slug}/{exp.id}: expected divergent answer"
            else:
                assert verify_answer == base_answer, f"{spec.slug}/{exp.id}: control replay diverged"
            db.delete(fork)
            db.commit()

        run = db.get(Run, run_id)
        run.experiments = experiments
        run.tools_used = sorted(
            {e.payload.get("tool") for e in events if e.type == EventType.TOOL_CALL if e.payload.get("tool")}
        )
        run.summary = spec.summary
        run.status = RunStatus.COMPLETED
        db.commit()

        bundle = export_run(run_id, db)
        return json.loads(bundle.model_dump_json())
    finally:
        db.close()


def main() -> None:
    init_db()
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    for spec in TRACES:
        bundle = record_trace(spec)
        out = TRACES_DIR / f"{spec.slug}.json"
        out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"recorded {spec.slug}: {len(bundle['events'])} events, "
              f"{len(bundle['llm_cache'])} llm-cache entries -> {out.relative_to(BACKEND)}")


if __name__ == "__main__":
    main()
