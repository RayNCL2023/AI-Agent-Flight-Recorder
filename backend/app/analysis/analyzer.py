"""Post-run analysis with explicit provenance.

Every verdict carries an `analysis_source` so the UI never passes one kind of
analysis off as another:

- "recorded"  — the branch reproduces a curated experiment; its label/diagnosis
                were recorded with the trace bundle.
- "llm"       — Live Mode with a real key: an actual LLM judged the branch.
- "heuristic" — deterministic rules over the event log (including the honest
                `unrecorded` verdict when replay left recorded coverage).
"""

import json
import logging
from collections import Counter

from ..bus import bus
from ..config import get_settings
from ..db import session_scope
from ..events import BranchLabel, BranchStatus, EventType, RunStatus
from ..models import Branch, Event, Run
from ..schemas import BranchOut, RunOut
from ..agent.llm import build_provider
from ..agent.replay import effective_events

logger = logging.getLogger("afr.analysis")


async def analyze_branch(branch_id: str) -> None:
    """Label a finished branch and generate a divergence diagnosis."""
    settings = get_settings()
    with session_scope() as db:
        branch = db.get(Branch, branch_id)
        if branch is None or branch.status in (BranchStatus.PENDING, BranchStatus.RUNNING):
            return
        events = effective_events(db, branch)
        parent = db.get(Branch, branch.parent_branch_id) if branch.parent_branch_id else None
        parent_events = effective_events(db, parent) if parent else []
        run = db.get(Run, branch.run_id)

        source = "heuristic"
        recorded = _matching_experiment(run, branch)
        if any(e.type == EventType.REPLAY_MISS for e in events):
            label, diagnosis = _unrecorded_analysis(branch)
        elif recorded is not None:
            label = BranchLabel(recorded.get("recorded_label", BranchLabel.UNLABELED))
            diagnosis = recorded.get("recorded_diagnosis") or ""
            source = "recorded"
        else:
            label, diagnosis = _heuristic_analysis(branch, events, parent, parent_events)
            if settings.live_available:
                try:
                    label, diagnosis = await _llm_analysis(branch, events, parent_events, label, diagnosis)
                    source = "llm"
                except Exception:
                    logger.exception("LLM analysis failed; keeping heuristic result")

        branch.label = label
        branch.diagnosis = diagnosis
        branch.analysis_source = source
        db.commit()
        await bus.publish(
            branch.run_id,
            {"kind": "branch_update", "branch": BranchOut.model_validate(branch).model_dump(mode="json")},
        )


async def summarize_run_if_settled(run_id: str) -> None:
    """Once every branch has settled, write a concise run summary."""
    settings = get_settings()
    with session_scope() as db:
        run = db.get(Run, run_id)
        if run is None or run.status not in (RunStatus.COMPLETED, RunStatus.FAILED):
            return
        summary = _heuristic_summary(db, run)
        if settings.live_available:
            try:
                summary = await _llm_summary(db, run)
            except Exception:
                logger.exception("LLM summary failed; keeping heuristic summary")
        run.summary = summary
        db.commit()
        await bus.publish(
            run_id,
            {"kind": "run_update", "run": RunOut.model_validate(run).model_dump(mode="json")},
        )


# ------------------------------------------------------------------- heuristics


def _matching_experiment(run: Run | None, branch: Branch) -> dict | None:
    """The curated experiment this fork reproduces, if any.

    A branch matches when it forked at the experiment's step with exactly the
    experiment's overrides — i.e. it replays the recorded variant end-to-end.
    """
    if run is None or branch.parent_branch_id is None:
        return None
    overrides = branch.overrides or {}
    for exp in run.experiments or []:
        if (
            branch.fork_seq == exp.get("fork_seq")
            and (overrides.get("edited_prompt") or None) == (exp.get("edited_prompt") or None)
            and (overrides.get("tool_overrides") or {}) == (exp.get("tool_overrides") or {})
        ):
            return exp
    return None


def _unrecorded_analysis(branch: Branch) -> tuple[BranchLabel, str]:
    diagnosis = (
        "Replay stopped honestly: the modification left the coverage of the "
        "recorded execution, and nothing is ever fabricated in Replay Mode. "
        "Try one of this trace's recorded experiments, or enable Live Mode "
        "with your own API key to execute new states for real."
    )
    if branch.parent_branch_id is None:
        diagnosis = (
            "Replay stopped honestly: this run has no recorded coverage for its "
            "execution state. Nothing is ever fabricated in Replay Mode."
        )
    return BranchLabel.UNRECORDED, diagnosis


def _heuristic_analysis(
    branch: Branch,
    events: list[Event],
    parent: Branch | None,
    parent_events: list[Event],
) -> tuple[BranchLabel, str]:
    completion = next((e for e in events if e.type == EventType.COMPLETION), None)
    errors = [e for e in events if e.type == EventType.ERROR]
    tool_calls = [e for e in events if e.type == EventType.TOOL_CALL]

    call_signatures = Counter(
        (e.payload.get("tool"), json.dumps(e.payload.get("arguments"), sort_keys=True))
        for e in tool_calls
    )
    looping = any(count >= 3 for count in call_signatures.values())

    empty_search_answered = completion is not None and any(
        e.type == EventType.TOOL_RESULT
        and e.payload.get("tool") == "web_search"
        and not (e.payload.get("output") or {}).get("results")
        for e in events
    )

    if branch.status == BranchStatus.FAILED or (completion is None and errors):
        label = BranchLabel.FAILED
        reason = errors[-1].payload.get("error", "unknown error") if errors else "no completion"
        diagnosis = f"Branch failed before producing an answer: {reason}."
    elif looping:
        label = BranchLabel.LOOP
        tool, _ = max(call_signatures, key=call_signatures.get)  # type: ignore[arg-type]
        diagnosis = f"The agent repeated the same `{tool}` call multiple times without making progress."
    elif empty_search_answered:
        label = BranchLabel.HALLUCINATION
        diagnosis = (
            "The final answer asserts facts although web_search returned zero results — "
            "the claim is not grounded in any tool evidence."
        )
    else:
        label = BranchLabel.SUCCESS
        diagnosis = "The agent gathered tool evidence and produced a grounded final answer."

    if parent is not None:
        diagnosis += " " + _divergence_note(branch, events, parent_events)
    return label, diagnosis


def _divergence_note(branch: Branch, events: list[Event], parent_events: list[Event]) -> str:
    overrides = branch.overrides or {}
    causes: list[str] = []
    if overrides.get("edited_prompt"):
        causes.append("the prompt was edited at the fork point")
    if overrides.get("tool_overrides"):
        causes.append(f"{len(overrides['tool_overrides'])} tool output(s) were replaced")
    cause = " and ".join(causes) if causes else "execution was replayed from the fork point"

    own = {e.id for e in events}
    first_new = next((e for e in events if e.seq == (branch.fork_seq or 0)), None)
    _ = own
    where = f" Divergence begins at step {branch.fork_seq}" + (
        f" ({first_new.name})." if first_new else "."
    )
    return f"Compared to its parent, {cause}.{where}"


def _heuristic_summary(db, run: Run) -> str:
    branches = run.branches
    labels = Counter(b.label for b in branches)
    total_events = sum(len(effective_events(db, b)) for b in branches)
    # Cost/token totals count each stored event once (not per-branch inheritance).
    from sqlalchemy import func, select

    total_tokens, total_cost = db.execute(
        select(
            func.coalesce(func.sum(Event.tokens_in + Event.tokens_out), 0),
            func.coalesce(func.sum(Event.cost_usd), 0.0),
        ).where(Event.run_id == run.id)
    ).one()

    label_text = ", ".join(f"{count}× {label}" for label, count in labels.items())
    return (
        f"Run “{run.title}” finished with {len(branches)} branch(es) ({label_text}). "
        f"{total_events} timeline events, {total_tokens} tokens, ${total_cost:.4f} total cost. "
        f"Prompt: “{run.prompt[:140]}”"
    )


# ------------------------------------------------------------------- LLM judge


_JUDGE_PROMPT = """You are a debugging assistant reviewing an AI agent execution trace.
Classify the branch as one of: success, hallucination, loop, failed.
Then explain in 2-3 sentences why the branch behaved as it did{divergence}.
Respond as JSON: {{"label": "...", "diagnosis": "..."}}

TRACE:
{trace}
"""


def _trace_text(events: list[Event], limit: int = 40) -> str:
    lines = []
    for e in events[:limit]:
        payload = json.dumps(e.payload, default=str)[:300]
        lines.append(f"[{e.seq}] {e.type} {e.name}: {payload}")
    return "\n".join(lines)


async def _llm_analysis(
    branch: Branch,
    events: list[Event],
    parent_events: list[Event],
    fallback_label: BranchLabel,
    fallback_diagnosis: str,
) -> tuple[BranchLabel, str]:
    provider = build_provider(get_settings())
    divergence = (
        ", and why it diverged from the parent branch it was forked from"
        if parent_events
        else ""
    )
    prompt = _JUDGE_PROMPT.format(divergence=divergence, trace=_trace_text(events))
    if parent_events:
        prompt += "\n\nPARENT TRACE:\n" + _trace_text(parent_events)

    response = await provider.complete(
        [{"role": "user", "content": prompt}], tools=[], seed=0
    )
    data = json.loads(_extract_json(response.content or "{}"))
    label = BranchLabel(data.get("label", fallback_label))
    diagnosis = str(data.get("diagnosis") or fallback_diagnosis)
    return label, diagnosis


async def _llm_summary(db, run: Run) -> str:
    provider = build_provider(get_settings())
    root = next((b for b in run.branches if b.parent_branch_id is None), None)
    trace = _trace_text(effective_events(db, root)) if root else ""
    response = await provider.complete(
        [
            {
                "role": "user",
                "content": "Summarise this AI agent run in 2 sentences for an engineer "
                f"scanning a run list. Prompt: {run.prompt}\n\nTRACE:\n{trace}",
            }
        ],
        tools=[],
        seed=0,
    )
    return (response.content or "").strip() or _heuristic_summary(db, run)


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end != -1 else "{}"
