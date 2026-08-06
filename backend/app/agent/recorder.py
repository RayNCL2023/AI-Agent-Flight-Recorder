"""Flight recorder: appends immutable events and publishes them to the SSE bus."""

import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from ..bus import bus
from ..events import EventType
from ..models import Branch, Event, Run
from ..schemas import BranchOut, EventOut, RunOut


class Recorder:
    """One recorder per executing branch. Not thread-safe; one engine owns it."""

    def __init__(self, db: Session, run: Run, branch: Branch, start_seq: int) -> None:
        self._db = db
        self._run = run
        self._branch = branch
        self._next_seq = start_seq
        self._last_event_id: str | None = None

    @property
    def last_event_id(self) -> str | None:
        return self._last_event_id

    def set_parent(self, event_id: str | None) -> None:
        """Anchor causality when resuming from a fork point."""
        self._last_event_id = event_id

    async def record(
        self,
        type_: EventType,
        name: str,
        payload: dict[str, Any],
        *,
        duration_ms: float = 0.0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        meta: dict[str, Any] | None = None,
    ) -> Event:
        event = Event(
            run_id=self._run.id,
            branch_id=self._branch.id,
            seq=self._next_seq,
            parent_event_id=self._last_event_id,
            trace_id=self._run.id,
            span_id=uuid.uuid4().hex,
            type=type_.value,
            name=name,
            duration_ms=round(duration_ms, 2),
            payload=payload,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            meta=meta or {},
        )
        self._db.add(event)
        self._db.commit()
        self._next_seq += 1
        self._last_event_id = event.id
        await bus.publish(
            self._run.id,
            {
                "kind": "event",
                "event": EventOut.model_validate(event).model_dump(mode="json"),
            },
        )
        return event

    async def publish_branch_update(self) -> None:
        await bus.publish(
            self._run.id,
            {
                "kind": "branch_update",
                "branch": BranchOut.model_validate(self._branch).model_dump(mode="json"),
            },
        )

    async def publish_run_update(self) -> None:
        await bus.publish(
            self._run.id,
            {
                "kind": "run_update",
                "run": RunOut.model_validate(self._run).model_dump(mode="json"),
            },
        )


class Stopwatch:
    def __init__(self) -> None:
        self._start = time.perf_counter()

    def lap_ms(self) -> float:
        now = time.perf_counter()
        elapsed = (now - self._start) * 1000
        self._start = now
        return elapsed
