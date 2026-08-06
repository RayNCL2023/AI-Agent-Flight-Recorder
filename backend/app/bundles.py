"""Trace bundles: importing v2 exports and loading the bundled library.

A bundle is a `RunExport` JSON document — run, branches, events and both replay
caches. The files in `app/traces/` are the recorded library shipped with the
demo; they are produced by `scripts/record_fixtures.py` running the real engine
over curated scripts, so every bundle replays through the production replay
path exactly as recorded.
"""

import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from .db import session_scope
from .models import Branch, Event, LLMCacheEntry, Run, ToolCacheEntry
from .schemas import RunExport

logger = logging.getLogger("afr.bundles")

TRACES_DIR = Path(__file__).parent / "traces"


def apply_import(db: Session, payload: RunExport) -> Run:
    """Insert a bundle into the database. Raises ValueError on id collision."""
    if db.get(Run, payload.run.id) is not None:
        raise ValueError("a run with this id already exists")
    run = Run(**payload.run.model_dump())
    db.add(run)
    # Cache entries have no ORM relationship to Run, so the unit of work would
    # not order their inserts after the run row; flush it first.
    db.flush()
    for b in payload.branches:
        db.add(Branch(**b.model_dump()))
    for e in payload.events:
        db.add(Event(**e.model_dump()))
    for t in payload.tool_cache:
        db.add(ToolCacheEntry(run_id=payload.run.id, **t.model_dump()))
    for c in payload.llm_cache:
        db.add(LLMCacheEntry(run_id=payload.run.id, **c.model_dump()))
    db.commit()
    db.refresh(run)
    return run


def load_bundled_traces() -> None:
    """Idempotently import every bundled trace whose run is not present yet."""
    if not TRACES_DIR.is_dir():
        return
    with session_scope() as db:
        for path in sorted(TRACES_DIR.glob("*.json")):
            payload = RunExport.model_validate(json.loads(path.read_text(encoding="utf-8")))
            if db.get(Run, payload.run.id) is not None:
                continue
            apply_import(db, payload)
            logger.info("loaded bundled trace %s (%s)", payload.run.title, path.name)
