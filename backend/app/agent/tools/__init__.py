"""Tool registry.

Every tool implements the `Tool` protocol: a name, a human description, a JSON
schema for its arguments, and a synchronous `run`. Tools must be deterministic
for a given (args, seed) pair — that property is what makes replay exact.
"""

from dataclasses import dataclass
from typing import Any, Callable

from .calculator import run_calculator
from .file_reader import run_file_reader
from .weather import run_weather
from .web_search import run_web_search


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema
    run: Callable[[dict[str, Any], int], dict[str, Any]]  # (args, seed) -> output


TOOLS: dict[str, Tool] = {
    "calculator": Tool(
        name="calculator",
        description="Evaluate an arithmetic expression. Supports + - * / ** % // and parentheses.",
        parameters={
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "e.g. (2+3)*4/1.5"}
            },
            "required": ["expression"],
        },
        run=run_calculator,
    ),
    "web_search": Tool(
        name="web_search",
        description="Search the web for a query. Returns ranked results with title, url and snippet.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        run=run_web_search,
    ),
    "file_reader": Tool(
        name="file_reader",
        description="Read a text file from the sandboxed sample_data directory.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "relative path"}},
            "required": ["path"],
        },
        run=run_file_reader,
    ),
    "weather": Tool(
        name="weather",
        description="Get current weather for a city (mock API, deterministic per seed).",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
        run=run_weather,
    ),
}


def openai_tool_specs() -> list[dict[str, Any]]:
    """Tool definitions in OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in TOOLS.values()
    ]
