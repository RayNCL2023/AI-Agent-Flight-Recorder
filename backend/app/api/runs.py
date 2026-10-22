"""Run lifecycle: library listing, live-run creation (gated), export/import.

Replay Mode never executes anything new: `POST /api/runs` refuses with an
explicit message instead of silently falling back to any offline generator.
Recorded library traces are immutable demo content and cannot be deleted.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..agent.engine import execute_branch
from ..agent.llm import model_name
from ..agent.replay import initial_messages
from ..bundles import apply_import
from ..config import get_settings
from ..db import get_db
from ..events import BranchStatus, RunStatus
from ..models import Branch, Event, LLMCacheEntry, Run, ToolCacheEntry
from ..schemas import (
    BranchOut,
    EventOut,
    LLMCacheOut,
    OkResponse,
    RunCreate,
    RunDetail,
    RunExport,
    RunListItem,
    RunOut,
    RunStats,
    ToolCacheOut,
)

router = APIRouter(prefix="/api/runs", tags=["runs"])

REPLAY_MODE_MESSAGE = (
    "Replay Mode is active: live execution is disabled and nothing is generated. "
    "Explore the recorded trace library, or start the server with AFR_MODE=live "
    "and your own API key to run new executions."
)

LIVE_UNAVAILABLE_MESSAGE = (
    "Live execution unavailable. Live Mode requires your own API key: set "
    "OPENAI_API_KEY (and optionally OPENAI_BASE_URL / LLM_MODEL) in backend/.env, "
    "then restart the server. Until then, the recorded trace library remains "
    "fully explorable."
)


@router.post("", response_model=RunDetail, status_code=201)
async def create_run(body: RunCreate, db: Session = Depends(get_db)) -> RunDetail:
    settings = get_settings()
    if settings.mode != "live":
        raise HTTPException(409, REPLAY_MODE_MESSAGE)
    if not settings.live_available:
        raise HTTPException(409, LIVE_UNAVAILABLE_MESSAGE)

    run = Run(
        title=body.title or body.prompt[:60],
        prompt=body.prompt,
        model=model_name(settings),
        seed=body.seed,
        status=RunStatus.PENDING,
        source="live",
    )
    root = Branch(name="main", status=BranchStatus.PENDING, color_index=0)
    run.branches.append(root)
    db.add(run)
    db.commit()
    db.refresh(run)

    asyncio.create_task(
        execute_branch(run.id, root.id, initial_messages(body.prompt), start_seq=1, parent_event_id=None)
    )
    return _detail(run)


@router.get("", response_model=list[RunListItem])
def list_runs(db: Session = Depends(get_db)) -> list[RunListItem]:
    runs = list(db.scalars(select(Run).order_by(Run.created_at.desc())))
    stats = {
        run_id: RunStats(
            events=events, tokens=tokens, cost_usd=round(cost, 8), duration_ms=round(ms, 2)
        )
        for run_id, events, tokens, cost, ms in db.execute(
            select(
                Event.run_id,
                func.count(),
                func.coalesce(func.sum(Event.tokens_in + Event.tokens_out), 0),
                func.coalesce(func.sum(Event.cost_usd), 0.0),
                func.coalesce(func.sum(Event.duration_ms), 0.0),
            ).group_by(Event.run_id)
        )
    }
    return [
        RunListItem(
            **RunOut.model_validate(run).model_dump(),
            stats=stats.get(run.id, RunStats()),
        )
        for run in runs
    ]


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: str, db: Session = Depends(get_db)) -> RunDetail:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return _detail(run)


@router.delete("/{run_id}", response_model=OkResponse)
def delete_run(run_id: str, db: Session = Depends(get_db)) -> OkResponse:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    if run.source == "recorded":
        raise HTTPException(
            409, "Recorded library traces are immutable demo content and cannot be deleted."
        )
    db.delete(run)
    db.commit()
    return OkResponse()


# ------------------------------------------------------------- export / import


@router.get("/{run_id}/export", response_model=RunExport)
def export_run(run_id: str, db: Session = Depends(get_db)) -> RunExport:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    events = list(db.scalars(select(Event).where(Event.run_id == run_id).order_by(Event.branch_id, Event.seq)))
    tool_cache = list(db.scalars(select(ToolCacheEntry).where(ToolCacheEntry.run_id == run_id)))
    llm_cache = list(db.scalars(select(LLMCacheEntry).where(LLMCacheEntry.run_id == run_id)))
    return RunExport(
        run=RunOut.model_validate(run),
        branches=[BranchOut.model_validate(b) for b in run.branches],
        events=[EventOut.model_validate(e) for e in events],
        tool_cache=[ToolCacheOut.model_validate(t) for t in tool_cache],
        llm_cache=[LLMCacheOut.model_validate(e) for e in llm_cache],
    )


@router.post("/import", response_model=RunDetail, status_code=201)
def import_run(payload: RunExport, db: Session = Depends(get_db)) -> RunDetail:
    try:
        run = apply_import(db, payload)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _detail(run)


def _detail(run: Run) -> RunDetail:
    return RunDetail(
        **RunOut.model_validate(run).model_dump(),
        branches=[BranchOut.model_validate(b) for b in run.branches],
    )
