"""Scripted provider for the trace-recording harness and the test suite.

This is NOT a runtime provider and is never returned by `build_provider`: users
of the app can never reach it. It exists so that recorded library traces can be
produced by running the *real* engine (real recorder, real tools, real caches)
over a curated script — which guarantees that every bundled trace is internally
consistent and replays byte-for-byte through the production replay path.
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .llm import LLMResponse, LLMToolCall, Message

SCRIPTED_MODEL = "scripted-demo-agent"


def estimate_tokens(text: str) -> int:
    """Cheap ~4 chars/token estimate used for scripted token accounting."""
    return max(1, len(text) // 4)


@dataclass(frozen=True)
class Turn:
    """One assistant step of a scripted execution.

    Either `tool_calls` (list of {"name", "arguments"}) or `content` (the final
    answer) must be set. `latency_ms` is really slept during recording so the
    trace carries genuine wall-clock timing.
    """

    reasoning: str | None = None
    content: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 600.0


class ScriptedProvider:
    """Plays a fixed list of turns, indexed by prior assistant messages."""

    def __init__(self, turns: list[Turn]) -> None:
        self._turns = turns

    async def complete(
        self, messages: list[Message], tools: list[dict], seed: int
    ) -> LLMResponse:
        step = sum(1 for m in messages if m.get("role") == "assistant")
        if step >= len(self._turns):
            raise RuntimeError(
                f"script exhausted: engine asked for turn {step + 1} of {len(self._turns)}"
            )
        turn = self._turns[step]
        await asyncio.sleep(turn.latency_ms / 1000)

        tool_calls = [
            LLMToolCall(
                id=_call_id(seed, step, i, tc),
                name=tc["name"],
                arguments=tc["arguments"],
            )
            for i, tc in enumerate(turn.tool_calls)
        ]
        tokens_in = sum(estimate_tokens(json.dumps(m, default=str)) for m in messages)
        tokens_out = estimate_tokens(
            (turn.reasoning or "") + (turn.content or "") + json.dumps(turn.tool_calls)
        )
        return LLMResponse(
            content=turn.content,
            reasoning=turn.reasoning,
            tool_calls=tool_calls,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=SCRIPTED_MODEL,
        )


def _call_id(seed: int, step: int, index: int, call: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps([seed, step, index, call], sort_keys=True).encode()
    ).hexdigest()
    return f"call_{digest[:12]}"
