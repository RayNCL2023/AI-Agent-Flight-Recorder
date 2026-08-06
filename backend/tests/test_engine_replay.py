"""Engine honesty: scripted recording, cache-only replay, replay_miss stops.

These tests drive `execute_branch` directly. Recording uses ScriptedProvider
(the harness path); replay passes provider=None (the Replay Mode path) so any
fabrication attempt would be impossible by construction.
"""

import asyncio

from app.agent.engine import execute_branch
from app.agent.replay import create_fork, effective_events, initial_messages
from app.agent.scripted import SCRIPTED_MODEL, ScriptedProvider, Turn
from app.db import SessionLocal
from app.events import BranchStatus
from app.models import Branch, LLMCacheEntry, Run
from app.schemas import ForkRequest

SCRIPT = [
    Turn(
        reasoning="The prompt asks for a height; searching for evidence.",
        tool_calls=[{"name": "web_search", "arguments": {"query": "Eiffel Tower height"}}],
        latency_ms=5,
    ),
    Turn(
        reasoning="One source is enough for a single fact.",
        content="The Eiffel Tower is 330 metres tall.",
        latency_ms=5,
    ),
]


def _record_scripted_run() -> tuple[str, str]:
    """Create a run and execute it with the scripted provider; return ids."""
    db = SessionLocal()
    try:
        run = Run(
            title="scripted",
            prompt="How tall is the Eiffel Tower?",
            model=SCRIPTED_MODEL,
            seed=7,
            source="recorded",
        )
        root = Branch(name="main", status=BranchStatus.PENDING, color_index=0)
        run.branches.append(root)
        db.add(run)
        db.commit()
        run_id, root_id = run.id, root.id
    finally:
        db.close()

    asyncio.run(
        execute_branch(
            run_id,
            root_id,
            initial_messages("How tall is the Eiffel Tower?"),
            start_seq=1,
            parent_event_id=None,
            provider=ScriptedProvider(SCRIPT),
        )
    )
    return run_id, root_id


def _signature(events) -> list[tuple]:
    """Timeline fingerprint ignoring replay bookkeeping (cached flag)."""
    return [
        (e.seq, e.type, {k: v for k, v in e.payload.items() if k != "cached"})
        for e in events
    ]


def test_scripted_recording_captures_trace_and_llm_cache(client):
    run_id, root_id = _record_scripted_run()
    db = SessionLocal()
    try:
        root = db.get(Branch, root_id)
        assert root.status == BranchStatus.COMPLETED
        types = [e.type for e in effective_events(db, root)]
        assert types[0] == "run_started"
        assert "tool_call" in types and "tool_result" in types
        assert types[-1] == "completion"
        cached = db.query(LLMCacheEntry).filter_by(run_id=run_id).count()
        assert cached == len(SCRIPT), "every completion must land in the LLM cache"
    finally:
        db.close()


def test_control_replay_reproduces_recording_without_a_provider(client):
    run_id, root_id = _record_scripted_run()
    db = SessionLocal()
    try:
        run = db.get(Run, run_id)
        root = db.get(Branch, root_id)
        original = _signature(effective_events(db, root))
        fork, messages, parent_event_id = create_fork(
            db, run, root, ForkRequest(fork_seq=1)
        )
        fork_id = fork.id
    finally:
        db.close()

    asyncio.run(
        execute_branch(run_id, fork_id, messages, 1, parent_event_id, provider=None)
    )

    db = SessionLocal()
    try:
        fork = db.get(Branch, fork_id)
        assert fork.status == BranchStatus.COMPLETED
        replayed = _signature(effective_events(db, fork))
        assert replayed == original, "control replay must reproduce the recording"
    finally:
        db.close()


def test_unrecorded_edit_stops_honestly_with_replay_miss(client):
    run_id, root_id = _record_scripted_run()
    db = SessionLocal()
    try:
        run = db.get(Run, run_id)
        root = db.get(Branch, root_id)
        fork, messages, parent_event_id = create_fork(
            db, run, root,
            ForkRequest(fork_seq=1, edited_prompt="Tell me about something unrecorded."),
        )
        fork_id = fork.id
    finally:
        db.close()

    asyncio.run(
        execute_branch(run_id, fork_id, messages, 1, parent_event_id, provider=None)
    )

    db = SessionLocal()
    try:
        fork = db.get(Branch, fork_id)
        assert fork.status == BranchStatus.FAILED
        events = effective_events(db, fork)
        types = [e.type for e in events]
        assert "replay_miss" in types
        assert "llm_message" not in types and "completion" not in types, (
            "nothing may be fabricated for an unrecorded state"
        )
        miss = next(e for e in events if e.type == "replay_miss")
        assert miss.payload["message"] == "No recorded execution matches this request."
    finally:
        db.close()
