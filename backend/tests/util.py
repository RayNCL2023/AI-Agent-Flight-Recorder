"""Shared helpers: record a small scripted run through the real engine."""

import asyncio

from app.agent.engine import execute_branch
from app.agent.replay import initial_messages
from app.agent.scripted import SCRIPTED_MODEL, ScriptedProvider, Turn
from app.db import SessionLocal
from app.events import BranchStatus
from app.models import Branch, Run

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

PROMPT = "How tall is the Eiffel Tower?"


def record_scripted_run(script: list[Turn] | None = None, prompt: str = PROMPT) -> tuple[str, str]:
    """Create a run and execute it with the scripted provider; return (run_id, root_id)."""
    db = SessionLocal()
    try:
        run = Run(
            title="scripted",
            prompt=prompt,
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
            initial_messages(prompt),
            start_seq=1,
            parent_event_id=None,
            provider=ScriptedProvider(script or SCRIPT),
        )
    )
    return run_id, root_id
