"""Fork resolution and deterministic replay.

A branch's *effective history* is assembled by walking its ancestor chain:
each ancestor contributes the events below the child's fork point, and the
branch contributes its own events. Nothing is ever copied — forks are O(1).

Replaying a fork = rebuild the OpenAI conversation from the effective history
below the fork point (applying the user's prompt edit / tool-output overrides),
then hand that state to the engine, which resumes the loop. Tool calls resolve
from the run-scoped cache, so anything the user did *not* change replays
identically.
"""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..events import BranchStatus, EventType
from ..models import Branch, Event, Run
from ..schemas import BranchDiff, DiffEntry, EventOut, ForkRequest
from .engine import SYSTEM_PROMPT
from .llm import Message

# ------------------------------------------------------------ effective history


def effective_events(db: Session, branch: Branch, up_to_seq: int | None = None) -> list[Event]:
    """Fully resolved event list for a branch (inherited + own), ordered by seq."""
    # Collect (branch_id, max_exclusive_seq) segments from root to leaf.
    segments: list[tuple[str, int | None]] = []
    cursor: Branch | None = branch
    limit: int | None = up_to_seq
    while cursor is not None:
        segments.append((cursor.id, limit))
        if cursor.parent_branch_id is None:
            break
        limit = cursor.fork_seq if limit is None else min(limit, cursor.fork_seq or limit)
        cursor = db.get(Branch, cursor.parent_branch_id)
    segments.reverse()

    events: list[Event] = []
    seen_seqs: set[int] = set()
    for branch_id, max_seq in segments:
        stmt = select(Event).where(Event.branch_id == branch_id).order_by(Event.seq)
        if max_seq is not None:
            stmt = stmt.where(Event.seq < max_seq)
        for ev in db.scalars(stmt):
            if ev.seq not in seen_seqs:  # child events shadow nothing; belt & braces
                events.append(ev)
                seen_seqs.add(ev.seq)
    events.sort(key=lambda e: e.seq)
    return events


# ------------------------------------------------------- conversation rebuilding


def rebuild_messages(
    events: list[Event],
    edited_prompt: str | None,
    tool_overrides: dict[str, dict],
) -> list[Message]:
    """Reconstruct the OpenAI conversation from recorded events.

    `tool_overrides` maps original tool_result event ids to replacement outputs;
    an override rewrites history exactly as if the tool had returned that value.
    """
    messages: list[Message] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for ev in events:
        etype = EventType(ev.type)
        if etype == EventType.RUN_STARTED:
            prompt = edited_prompt if edited_prompt is not None else ev.payload.get("prompt", "")
            messages.append({"role": "user", "content": prompt})
        elif etype == EventType.LLM_MESSAGE:
            tool_calls = ev.payload.get("tool_calls") or []
            messages.append(
                {
                    "role": "assistant",
                    "content": ev.payload.get("content"),
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["arguments"]),
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )
        elif etype == EventType.TOOL_RESULT:
            output = tool_overrides.get(ev.id, ev.payload.get("output", {}))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": ev.payload.get("tool_call_id", ""),
                    "content": json.dumps(output, default=str),
                }
            )
        elif etype == EventType.COMPLETION:
            messages.append({"role": "assistant", "content": ev.payload.get("content", "")})
        # reasoning / tool_call / retry / error events are recorder-only detail:
        # they have no counterpart in the provider conversation format.
    return messages


# ----------------------------------------------------------------------- forking


def create_fork(db: Session, run: Run, source: Branch, req: ForkRequest) -> tuple[Branch, list[Message], str | None]:
    """Create the fork branch and return (branch, rebuilt messages, parent event id).

    fork_seq == 1 means "replay from the very beginning": the fork starts as a
    fresh conversation (optionally with an edited prompt) and records its own
    run_started event instead of inheriting anything.
    """
    history = effective_events(db, source, up_to_seq=req.fork_seq)
    branch_count = len(run.branches)
    overrides = {
        "edited_prompt": req.edited_prompt,
        "tool_overrides": req.tool_overrides,
    }
    fork = Branch(
        run_id=run.id,
        name=req.name or f"fork-{branch_count}",
        parent_branch_id=source.id,
        fork_seq=req.fork_seq,
        overrides=overrides,
        status=BranchStatus.PENDING,
        color_index=branch_count % 6,
    )
    db.add(fork)
    db.commit()
    db.refresh(fork)

    if not history:
        prompt = req.edited_prompt if req.edited_prompt is not None else run.prompt
        return fork, initial_messages(prompt), None

    messages = rebuild_messages(history, req.edited_prompt, req.tool_overrides)
    parent_event_id = history[-1].id
    return fork, messages, parent_event_id


def initial_messages(prompt: str) -> list[Message]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]


# -------------------------------------------------------------------------- diff


def diff_branches(db: Session, a: Branch, b: Branch) -> BranchDiff:
    """Align two branches' effective histories for side-by-side comparison.

    Events sharing identical (type, payload) at the same position are "same";
    same position but different content is "changed"; leftovers are additions.
    """
    events_a = effective_events(db, a)
    events_b = effective_events(db, b)

    fork_seq = b.fork_seq if b.parent_branch_id == a.id else (
        a.fork_seq if a.parent_branch_id == b.id else None
    )

    entries: list[DiffEntry] = []
    for i in range(max(len(events_a), len(events_b))):
        ev_a = events_a[i] if i < len(events_a) else None
        ev_b = events_b[i] if i < len(events_b) else None
        if ev_a is not None and ev_b is not None:
            if ev_a.id == ev_b.id:
                kind = "same"  # literally the same shared row pre-fork
            elif ev_a.type == ev_b.type and _norm(ev_a.payload) == _norm(ev_b.payload):
                kind = "same"
            else:
                kind = "changed"
            entries.append(
                DiffEntry(
                    kind=kind,
                    a=EventOut.model_validate(ev_a),
                    b=EventOut.model_validate(ev_b),
                )
            )
        elif ev_a is not None:
            entries.append(DiffEntry(kind="added_a", a=EventOut.model_validate(ev_a)))
        elif ev_b is not None:
            entries.append(DiffEntry(kind="added_b", b=EventOut.model_validate(ev_b)))

    return BranchDiff(branch_a=a.id, branch_b=b.id, fork_seq=fork_seq, entries=entries)


def _norm(payload: dict) -> dict:
    """Drop keys that vary between live and replayed execution without being
    semantic divergence (a cache hit returns the identical output)."""
    return {k: v for k, v in payload.items() if k != "cached"}
