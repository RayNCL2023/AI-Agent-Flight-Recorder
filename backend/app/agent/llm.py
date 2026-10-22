"""LLM provider abstraction.

Exactly one runtime implementation: `OpenAICompatProvider`, used in Live Mode
against any OpenAI-compatible /chat/completions endpoint (OpenAI, Azure, vLLM,
Ollama, LM Studio…). In Replay Mode there is **no provider at all** — the engine
resolves every completion from the recorded LLM cache and stops with an honest
`replay_miss` event when a conversation state has no recorded coverage. Nothing
in this application fabricates model output.
"""

import json
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


def build_provider(settings: Settings) -> LLMProvider | None:
    """The live provider, or None when execution must resolve from recordings.

    Returning None is deliberate for `mode=live` without a key too: live is
    never silently downgraded to anything that generates output — the API layer
    refuses new runs and replays stay recording-only.
    """
    if settings.live_available:
        return OpenAICompatProvider(settings)
    return None


def model_name(settings: Settings) -> str:
    return settings.llm_model
