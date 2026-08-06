"""Server-Sent Events stream of live recorder events for a run."""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..bus import bus

router = APIRouter(prefix="/api/stream", tags=["stream"])

_HEARTBEAT_SECONDS = 15.0


@router.get("/runs/{run_id}")
async def stream_run(run_id: str, request: Request) -> StreamingResponse:
    async def event_source():
        yield "retry: 2000\n\n"
        subscription = bus.subscribe(run_id)
        iterator = subscription.__aiter__()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(
                        iterator.__anext__(), timeout=_HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                yield bus.sse_format(message)
        finally:
            await iterator.aclose()

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
