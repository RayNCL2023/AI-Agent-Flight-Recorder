"""LLM provider abstraction.

Two implementations:

- `OpenAICompatProvider` — any OpenAI-compatible /chat/completions endpoint
  (OpenAI, Azure, vLLM, Ollama, LM Studio…), configured via env vars.
- `MockProvider` — a fully deterministic, seeded, offline provider so the whole
  application can be demoed without an API key. It plans tool calls from the
  user prompt and synthesises its final answer *from the tool results present in
  the conversation*, which is what makes forked tool-output edits visibly change
  the outcome downstream.
"""

import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from ..config import Settings

Message = dict[str, Any]  # OpenAI chat message shape


@dataclass(frozen=True)
class LLMToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    content: str | None
    reasoning: str | None
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = "unknown"


class LLMProvider(Protocol):
    async def complete(
        self, messages: list[Message], tools: list[dict], seed: int
    ) -> LLMResponse: ...


def _estimate_tokens(text: str) -> int:
    """Cheap ~4 chars/token estimate for the mock provider."""
    return max(1, len(text) // 4)


# --------------------------------------------------------------- OpenAI-compatible


class OpenAICompatProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def complete(
        self, messages: list[Message], tools: list[dict], seed: int
    ) -> LLMResponse:
        s = self._settings
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{s.openai_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {s.openai_api_key}"},
                json={
                    "model": s.llm_model,
                    "messages": messages,
                    "tools": tools,
                    "temperature": s.llm_temperature,
                    "max_tokens": s.llm_max_tokens,
                    "seed": seed,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]["message"]
        usage = data.get("usage", {})
        tool_calls = [
            LLMToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=json.loads(tc["function"]["arguments"] or "{}"),
            )
            for tc in choice.get("tool_calls") or []
        ]
        return LLMResponse(
            content=choice.get("content"),
            reasoning=None,
            tool_calls=tool_calls,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            model=data.get("model", s.llm_model),
        )


# --------------------------------------------------------------------------- mock


_MATH_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?(?:\s*[-+*/%]\s*\(?\s*\d+(?:\.\d+)?\s*\)?)+)")
_WEATHER_RE = re.compile(r"weather\s+(?:in|at|for)\s+([A-Za-zÀ-ÿ' -]+?)(?:[?,.]|$)", re.I)
_FILE_RE = re.compile(r"([\w./-]+\.(?:txt|md|csv|json|log))", re.I)

MOCK_MODEL = "mock-agent-v1"


class MockProvider:
    """Deterministic scripted agent brain. Same inputs + seed => same outputs."""

    async def complete(
        self, messages: list[Message], tools: list[dict], seed: int
    ) -> LLMResponse:
        prompt = _last_user_content(messages)
        rng = random.Random(f"{seed}::{hashlib.sha256(prompt.encode()).hexdigest()}")

        planned = _plan_tool_calls(prompt)
        done = _completed_tool_calls(messages)
        pending = [p for p in planned if _call_key(p) not in done]

        tokens_in = sum(_estimate_tokens(json.dumps(m, default=str)) for m in messages)

        if pending:
            call = pending[0]
            step_no = len(done) + 1
            reasoning = _reasoning_for(call, step_no, len(planned), rng)
            tool_call = LLMToolCall(
                id=f"call_{hashlib.sha256(json.dumps([seed, step_no, call], sort_keys=True).encode()).hexdigest()[:12]}",
                name=call["name"],
                arguments=call["arguments"],
            )
            return LLMResponse(
                content=None,
                reasoning=reasoning,
                tool_calls=[tool_call],
                tokens_in=tokens_in,
                tokens_out=_estimate_tokens(reasoning) + 24,
                model=MOCK_MODEL,
            )

        answer = _synthesise_answer(prompt, messages, rng)
        return LLMResponse(
            content=answer,
            reasoning="All required information gathered — composing the final answer.",
            tool_calls=[],
            tokens_in=tokens_in,
            tokens_out=_estimate_tokens(answer),
            model=MOCK_MODEL,
        )


def _last_user_content(messages: list[Message]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return str(m.get("content", ""))
    return ""


def _plan_tool_calls(prompt: str) -> list[dict[str, Any]]:
    """Derive an ordered tool plan from the prompt. Purely lexical, fully stable."""
    plan: list[dict[str, Any]] = []
    if m := _MATH_RE.search(prompt):
        plan.append({"name": "calculator", "arguments": {"expression": m.group(1).strip()}})
    if m := _WEATHER_RE.search(prompt):
        plan.append({"name": "weather", "arguments": {"city": m.group(1).strip().title()}})
    if m := _FILE_RE.search(prompt):
        plan.append({"name": "file_reader", "arguments": {"path": m.group(1)}})
    lowered = prompt.lower()
    wants_search = any(
        k in lowered for k in ("search", "look up", "find out", "who", "what", "when", "where", "how tall", "how high", "capital", "gdp")
    )
    if wants_search or not plan:
        query = re.sub(r"[?.!]", "", prompt).strip()
        plan.append({"name": "web_search", "arguments": {"query": query[:120]}})
    return plan


def _call_key(call: dict[str, Any]) -> str:
    return f"{call['name']}::{json.dumps(call['arguments'], sort_keys=True)}"


def _completed_tool_calls(messages: list[Message]) -> set[str]:
    """Keys of tool calls that already have a result in the conversation."""
    done: set[str] = set()
    calls_by_id: dict[str, dict[str, Any]] = {}
    for m in messages:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                calls_by_id[tc["id"]] = {
                    "name": tc["function"]["name"],
                    "arguments": json.loads(tc["function"]["arguments"] or "{}"),
                }
        elif m.get("role") == "tool" and m.get("tool_call_id") in calls_by_id:
            done.add(_call_key(calls_by_id[m["tool_call_id"]]))
    return done


_REASONING_TEMPLATES = [
    "Step {step}/{total}: I need external data here — invoking `{tool}` with {args}.",
    "Step {step}/{total}: the prompt requires `{tool}`; calling it with {args}.",
    "Step {step}/{total}: delegating to `{tool}` ({args}) before I can answer.",
]


def _reasoning_for(call: dict[str, Any], step: int, total: int, rng: random.Random) -> str:
    template = rng.choice(_REASONING_TEMPLATES)
    return template.format(
        step=step, total=total, tool=call["name"], args=json.dumps(call["arguments"])
    )


def _tool_outputs(messages: list[Message]) -> list[tuple[str, dict[str, Any]]]:
    """(tool_name, parsed_output) pairs in conversation order."""
    names_by_id: dict[str, str] = {}
    outputs: list[tuple[str, dict[str, Any]]] = []
    for m in messages:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                names_by_id[tc["id"]] = tc["function"]["name"]
        elif m.get("role") == "tool":
            try:
                parsed = json.loads(m.get("content") or "{}")
            except json.JSONDecodeError:
                parsed = {"raw": m.get("content")}
            outputs.append((names_by_id.get(m.get("tool_call_id", ""), "unknown"), parsed))
    return outputs


def _synthesise_answer(prompt: str, messages: list[Message], rng: random.Random) -> str:
    parts: list[str] = []
    for tool, out in _tool_outputs(messages):
        if isinstance(out, dict) and out.get("error"):
            parts.append(f"The `{tool}` step failed ({out['error']}), so that part is unresolved.")
        elif tool == "calculator":
            parts.append(f"{out.get('expression')} = **{out.get('result')}**.")
        elif tool == "weather":
            parts.append(
                f"Weather in {out.get('city')}: {out.get('condition')}, "
                f"{out.get('temperature_c')}°C, humidity {out.get('humidity_pct')}%, "
                f"wind {out.get('wind_kph')} kph."
            )
        elif tool == "file_reader":
            content = str(out.get("content", ""))
            first_line = content.splitlines()[0] if content else "(empty)"
            parts.append(
                f"Read `{out.get('path')}` ({out.get('size_bytes')} bytes); it begins: “{first_line[:120]}”."
            )
        elif tool == "web_search":
            results = out.get("results") or []
            if results:
                top = results[0]
                parts.append(f"According to {top['title']}: {top['snippet']}")
            else:
                # Deliberate failure mode: with no evidence the mock model
                # fabricates a confident claim — great fodder for the
                # "Hallucination" branch label in the analyzer.
                parts.append(
                    f"Although no sources were found, it is widely known that {out.get('query', 'this')} "
                    f"was first documented in {rng.randint(1850, 1990)}."
                )
        else:
            parts.append(f"`{tool}` returned: {json.dumps(out)[:160]}")
    if not parts:
        return "I could not gather any information for this request."
    opener = rng.choice(["Here is what I found:", "Summary of findings:", "Done — results:"])
    return opener + "\n\n" + "\n".join(f"- {p}" for p in parts)


# ------------------------------------------------------------------------ factory


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("LLM_PROVIDER=openai requires OPENAI_API_KEY")
        return OpenAICompatProvider(settings)
    return MockProvider()


def model_name(settings: Settings) -> str:
    return settings.llm_model if settings.llm_provider == "openai" else MOCK_MODEL
