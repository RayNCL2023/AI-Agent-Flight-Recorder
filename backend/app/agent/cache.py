"""Deterministic tool-output cache.

The first live execution of a (tool, args) pair within a run is persisted; every
replay of that run — on any branch — resolves the same call from cache instead
of re-executing. Combined with seeded randomness this makes replays exact.
"""

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ToolCacheEntry


def cache_key(tool: str, args: dict[str, Any]) -> str:
    canonical = json.dumps({"tool": tool, "args": args}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def lookup(db: Session, run_id: str, tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
    entry = db.scalar(
        select(ToolCacheEntry).where(
            ToolCacheEntry.run_id == run_id,
            ToolCacheEntry.cache_key == cache_key(tool, args),
        )
    )
    return entry.output if entry else None


def store(db: Session, run_id: str, tool: str, args: dict[str, Any], output: dict[str, Any]) -> None:
    if lookup(db, run_id, tool, args) is not None:
        return  # first write wins; the cache is immutable like the event log
    db.add(
        ToolCacheEntry(
            run_id=run_id,
            cache_key=cache_key(tool, args),
            tool=tool,
            args=args,
            output=output,
        )
    )
    db.commit()
