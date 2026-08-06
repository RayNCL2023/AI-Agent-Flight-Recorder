"""The agent execution engine.

Runs one branch to completion: a classic plan → act → observe loop where every
step is recorded as an immutable event. The engine is oblivious to whether it is
executing a fresh run or a fork — it just receives a starting conversation
state, a starting sequence number, and a causal parent event.
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
from .cache import lookup as cache_lookup, store as cache_store
from .llm import LLMResponse, Message, build_provider, model_name
from .recorder import Recorder, Stopwatch
from .tools import TOOLS, openai_tool_specs

logger = logging.getLogger("afr.engine")

SYSTEM_PROMPT = (
    "You are a precise research agent. Use the available tools to gather facts, "
    "then answer concisely. Prefer tool evidence over memory. When you have "
    "enough information, reply with the final answer instead of calling tools."
)


async def execute_branch(
    run_id: str,
    branch_id: str,
    messages: list[Message],
    start_seq: int,
    parent_event_id: str | None,
) -> None:
    """Entry point scheduled as an asyncio task. Owns its own DB session."""
    settings = get_settings()
    provider = build_provider(settings)
    model = model_name(settings)

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
                await recorder.record(
                    EventType.RUN_STARTED,
                    "run started",
                    {"prompt": messages[-1]["content"], "model": model, "seed": run.seed},
                    meta={"provider": settings.llm_provider},
                )
            completed = await _agent_loop(
                db, recorder, provider, model, messages, run, branch, settings
            )
            branch.status = BranchStatus.COMPLETED if completed else BranchStatus.FAILED
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
    provider,
    model: str,
    messages: list[Message],
    run: Run,
    branch: Branch,
    settings,
) -> bool:
    """Returns True if the branch reached a completion event."""
    tool_specs = openai_tool_specs()

    for _step in range(settings.agent_max_steps):
        watch = Stopwatch()
        response: LLMResponse = await provider.complete(messages, tool_specs, run.seed)
        llm_ms = watch.lap_ms()
        step_cost = cost_usd(model, response.tokens_in, response.tokens_out)

        if response.reasoning:
            await recorder.record(
                EventType.REASONING,
                "reasoning",
                {"text": response.reasoning},
                meta={"model": model},
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
                meta={"model": model},
            )
            messages.append(_assistant_message(response))
            for tc in response.tool_calls:
                output = await _execute_tool(
                    db, recorder, run, tc.id, tc.name, tc.arguments
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
            meta={"model": model},
        )
        return True

    await recorder.record(
        EventType.ERROR,
        "max steps exceeded",
        {"error": f"agent did not converge within {settings.agent_max_steps} steps"},
    )
    return False


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
) -> dict[str, Any]:
    """Run a tool with cache-first resolution, one retry, and full recording."""
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
