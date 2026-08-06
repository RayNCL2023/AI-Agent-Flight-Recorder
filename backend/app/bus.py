"""In-process pub/sub bus feeding Server-Sent Events subscribers.

Each subscriber gets its own asyncio queue; the agent engine publishes recorder
events keyed by run id. This is deliberately in-memory — a single-process
deployment is the target; swap for Redis pub/sub if you ever scale out.
"""

import asyncio
import json
from collections import defaultdict
from typing import Any, AsyncIterator


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def publish(self, run_id: str, message: dict[str, Any]) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(run_id, ()))
        for q in queues:
            # Never block the engine on a slow consumer.
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                pass

    async def subscribe(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        async with self._lock:
            self._subscribers[run_id].add(q)
        try:
            while True:
                message = await q.get()
                yield message
        finally:
            async with self._lock:
                self._subscribers[run_id].discard(q)

    @staticmethod
    def sse_format(message: dict[str, Any]) -> str:
        """Serialise a message as a text/event-stream frame."""
        return f"event: {message.get('kind', 'message')}\ndata: {json.dumps(message, default=str)}\n\n"


bus = EventBus()
