"""The agent execution engine.

Runs one branch to completion: a plan → act → observe loop where every step is
recorded as an immutable event. The engine is oblivious to whether it is
executing a fresh run or a fork — it just receives a starting conversation
state, a starting sequence number, and a causal parent event.

Honesty contract: with no live provider (Replay Mode), every LLM completion must
resolve from the recorded LLM cache and every tool call from the recorded tool
cache. Any conversation state outside recorded coverage records a `replay_miss`
event and fails the branch — the engine never fabricates a continuation.
"""

import asyncio
import json
import logging
from typing import Any

from ..config import get_settings
from ..db import session_scope
from ..events import BranchStatus, EventType, RunStatus
from ..models import Branch, Run
from ..pricing import cost_usd
from . import llm_cache
from .cache import lookup as cache_lookup, store as cache_store
from .llm import LLMProvider, LLMResponse, LLMToolCall, Message, build_provider
from .recorder import Recorder, Stopwatch
from .tools import TOOLS, openai_tool_specs

logger = logging.getLogger("afr.engine")

SYSTEM_PROMPT = (
    "You are a precise research agent. Use the available tools to gather facts, "
    "then answer concisely. Prefer tool evidence over memory. When you have "
    "enough information, reply with the final answer instead of calling tools."
)

REPLAY_MISS_MESSAGE = "No recorded execution matches this request."


class _ReplayMiss(Exception):
    """Raised after a replay_miss event has been recorded; aborts the branch."""


async def execute_branch(
    run_id: str,
    branch_id: str,
    messages: list[Message],
    start_seq: int,
    parent_event_id: str | None,
    provider: LLMProvider | None = None,
) -> None:
    """Entry point scheduled as an asyncio task. Owns its own DB session.

    `provider` is injected by the recording harness and tests; normal operation
    builds it from settings — which yields None in Replay Mode, making this a
    pure replay of recorded material.
    """
    settings = get_settings()
    if provider is None:
        provider = build_provider(settings)

    with session_scope() as db:
        run = db.get(Run, run_id)
        branch = db.get(Branch, branch_id)
        if run is None or branch is None:
            logger.error("run or branch vanished before execution: %s/%s", run_id, branch_id)
            return

        recorder = Recorder(db, run, branch, start_seq)
        recorder.set_parent(parent_event_id)

        branch.status = BranchStatus.RUNNING
        run.status = RunStatus.RUNNING
        db.commit()
        await recorder.publish_run_update()
        await recorder.publish_branch_update()

        try:
            if start_seq == 1:
                system_prompt = (
                    messages[0]["content"] if messages and messages[0].get("role") == "system" else None
                )
                await recorder.record(
                    EventType.RUN_STARTED,
                    "run started",
                    {
                        "prompt": messages[-1]["content"],
                        "system_prompt": system_prompt,
                        "model": run.model,
                        "seed": run.seed,
                    },
                    meta={"mode": settings.mode, "live": provider is not None},
                )
            completed = await _agent_loop(
                db, recorder, provider, messages, run, branch, settings
            )
            branch.status = BranchStatus.COMPLETED if completed else BranchStatus.FAILED
        except _ReplayMiss:
            branch.status = BranchStatus.FAILED
        except Exception as exc:  # engine-level failure: record, never crash the app
            logger.exception("branch %s failed", branch_id)
            await recorder.record(
                EventType.ERROR,
                "engine failure",
                {"error": str(exc), "recoverable": False},
            )
            branch.status = BranchStatus.FAILED

        _settle_run_status(db, run)
        db.commit()
        await recorder.publish_branch_update()
        await recorder.publish_run_update()

    # Post-run analysis runs outside the engine session and never blocks it.
    from ..analysis.analyzer import analyze_branch, summarize_run_if_settled

    try:
        await analyze_branch(branch_id)
        await summarize_run_if_settled(run_id)
    except Exception:
        logger.exception("post-run analysis failed for branch %s", branch_id)


async def _agent_loop(
    db,
    recorder: Recorder,
    provider: LLMProvider | None,
    messages: list[Message],
    run: Run,
    branch: Branch,
    settings,
) -> bool:
    """Returns True if the branch reached a completion event."""
    tool_specs = openai_tool_specs()
    live = provider is not None

    for _step in range(settings.agent_max_steps):
        response, llm_ms, replayed = await _next_completion(
            db, recorder, provider, messages, run
        )
        step_cost = cost_usd(run.model, response.tokens_in, response.tokens_out)
        llm_meta = {"model": run.model, "replayed": replayed}

        if response.reasoning:
            await recorder.record(
                EventType.REASONING,
                "reasoning",
                {"text": response.reasoning},
                meta=llm_meta,
            )

        if response.tool_calls:
            await recorder.record(
                EventType.LLM_MESSAGE,
                "assistant message",
                {
                    "content": response.content,
                    "tool_calls": [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in response.tool_calls
                    ],
                },
                duration_ms=llm_ms,
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                cost_usd=step_cost,
                meta=llm_meta,
            )
            messages.append(_assistant_message(response))
            for tc in response.tool_calls:
                output = await _execute_tool(
                    db, recorder, run, tc.id, tc.name, tc.arguments, live
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(output, default=str),
                    }
                )
            continue

        # No tool calls => the model is answering. Terminal event for the branch.
        await recorder.record(
            EventType.COMPLETION,
            "final answer",
            {"content": response.content or ""},
            duration_ms=llm_ms,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_usd=step_cost,
            meta=llm_meta,
        )
        return True

    await recorder.record(
        EventType.ERROR,
        "max steps exceeded",
        {"error": f"agent did not converge within {settings.agent_max_steps} steps"},
    )
    return False


async def _next_completion(
    db,
    recorder: Recorder,
    provider: LLMProvider | None,
    messages: list[Message],
    run: Run,
) -> tuple[LLMResponse, float, bool]:
    """Resolve the next LLM step: recorded cache first, live provider second.

    Returns (response, latency_ms, replayed). Replayed steps report the original
    recorded latency. A cache miss with no provider records a replay_miss.
    """
    key = llm_cache.cache_key(run.model, run.seed, messages)
    cached = llm_cache.lookup(db, run.id, key)
    if cached is not None:
        return _response_from_cache(cached), float(cached.get("duration_ms", 0.0)), True

    if provider is None:
        await recorder.record(
            EventType.REPLAY_MISS,
            "no recorded execution",
            {
                "message": REPLAY_MISS_MESSAGE,
                "context": "llm",
                "detail": (
                    "This conversation state has no recorded completion, so replay "
                    "stops here instead of fabricating one. Recorded experiments for "
                    "this trace replay end-to-end; enable Live Mode with an API key "
                    "to execute new states for real."
                ),
            },
        )
        raise _ReplayMiss()

    watch = Stopwatch()
    response = await provider.complete(messages, openai_tool_specs(), run.seed)
    llm_ms = watch.lap_ms()
    llm_cache.store(db, run.id, key, _response_to_cache(response, llm_ms))
    return response, llm_ms, False


def _response_to_cache(response: LLMResponse, duration_ms: float) -> dict[str, Any]:
    return {
        "content": response.content,
        "reasoning": response.reasoning,
        "tool_calls": [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in response.tool_calls
        ],
        "tokens_in": response.tokens_in,
        "tokens_out": response.tokens_out,
        "model": response.model,
        "duration_ms": round(duration_ms, 2),
    }


def _response_from_cache(cached: dict[str, Any]) -> LLMResponse:
    return LLMResponse(
        content=cached.get("content"),
        reasoning=cached.get("reasoning"),
        tool_calls=[
            LLMToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
            for tc in cached.get("tool_calls", [])
        ],
        tokens_in=int(cached.get("tokens_in", 0)),
        tokens_out=int(cached.get("tokens_out", 0)),
        model=str(cached.get("model", "recorded")),
    )


def _assistant_message(response: LLMResponse) -> Message:
    return {
        "role": "assistant",
        "content": response.content,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in response.tool_calls
        ],
    }


async def _execute_tool(
    db,
    recorder: Recorder,
    run: Run,
    tool_call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    live: bool,
) -> dict[str, Any]:
    """Resolve a tool call: recorded cache first; live execution only in Live Mode."""
    settings = get_settings()
    await recorder.record(
        EventType.TOOL_CALL,
        f"call {tool_name}",
        {"tool": tool_name, "arguments": arguments, "tool_call_id": tool_call_id},
    )

    cached = cache_lookup(db, run.id, tool_name, arguments)
    if cached is not None:
        await recorder.record(
            EventType.TOOL_RESULT,
            f"{tool_name} result (cached)",
            {
                "tool": tool_name,
                "output": cached,
                "cached": True,
                "tool_call_id": tool_call_id,
            },
        )
        return cached

    if not live:
        await recorder.record(
            EventType.REPLAY_MISS,
            "no recorded execution",
            {
                "message": REPLAY_MISS_MESSAGE,
                "context": "tool",
                "detail": (
                    f"`{tool_name}` was asked for arguments that no recorded "
                    "execution of this trace ever produced, so replay stops here "
                    "instead of running the tool live."
                ),
            },
        )
        raise _ReplayMiss()

    tool = TOOLS.get(tool_name)
    if tool is None:
        output = {"error": f"unknown tool: {tool_name}"}
        await recorder.record(
            EventType.ERROR, f"unknown tool {tool_name}", {"error": output["error"]}
        )
        return output

    attempts = settings.agent_tool_retry_limit + 1
    last_error = ""
    for attempt in range(attempts):
        watch = Stopwatch()
        try:
            # Tools are synchronous and fast; run in a thread to keep the loop live.
            output = await asyncio.to_thread(tool.run, arguments, run.seed)
            cache_store(db, run.id, tool_name, arguments, output)
            await recorder.record(
                EventType.TOOL_RESULT,
                f"{tool_name} result",
                {
                    "tool": tool_name,
                    "output": output,
                    "cached": False,
                    "tool_call_id": tool_call_id,
                },
                duration_ms=watch.lap_ms(),
            )
            return output
        except Exception as exc:
            last_error = str(exc)
            await recorder.record(
                EventType.ERROR,
                f"{tool_name} failed",
                {"error": last_error, "recoverable": attempt < attempts - 1},
                duration_ms=watch.lap_ms(),
            )
            if attempt < attempts - 1:
                await recorder.record(
                    EventType.RETRY,
                    f"retrying {tool_name}",
                    {"tool": tool_name, "attempt": attempt + 2, "of": attempts},
                )

    output = {"error": last_error}
    cache_store(db, run.id, tool_name, arguments, output)
    await recorder.record(
        EventType.TOOL_RESULT,
        f"{tool_name} result (error)",
        {
            "tool": tool_name,
            "output": output,
            "cached": False,
            "tool_call_id": tool_call_id,
        },
    )
    return output


def _settle_run_status(db, run: Run) -> None:
    """A run is settled when no branch is still pending/running."""
    statuses = {b.status for b in run.branches}
    if statuses & {BranchStatus.PENDING, BranchStatus.RUNNING}:
        run.status = RunStatus.RUNNING
    elif BranchStatus.COMPLETED in statuses:
        run.status = RunStatus.COMPLETED
    else:
        run.status = RunStatus.FAILED
