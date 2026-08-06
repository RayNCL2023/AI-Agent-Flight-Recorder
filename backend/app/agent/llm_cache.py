"""Deterministic-replay cache for LLM completions.

The counterpart of the tool-output cache (`agent/cache.py`) for the model side
of the loop. Every completion produced during a *recorded* execution is stored
under a hash of the exact conversation state that produced it. Replay resolves
each step from this cache; a state with no entry means the recording does not
cover it, and the engine stops honestly instead of fabricating a continuation.
"""

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LLMCacheEntry

Message = dict[str, Any]


def cache_key(model: str, seed: int, messages: list[Message]) -> str:
    canonical = json.dumps(
        {"model": model, "seed": seed, "messages": messages},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def lookup(db: Session, run_id: str, key: str) -> dict[str, Any] | None:
    entry = db.scalar(
        select(LLMCacheEntry).where(
            LLMCacheEntry.run_id == run_id,
            LLMCacheEntry.cache_key == key,
        )
    )
    return entry.response if entry else None


def store(db: Session, run_id: str, key: str, response: dict[str, Any]) -> None:
    if lookup(db, run_id, key) is not None:
        return  # first write wins; the cache is immutable like the event log
    db.add(LLMCacheEntry(run_id=run_id, cache_key=key, response=response))
    db.commit()
