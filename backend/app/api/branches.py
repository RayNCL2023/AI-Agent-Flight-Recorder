"""Branch timeline, fork/replay, diff and analysis endpoints."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..agent.engine import execute_branch
from ..agent.replay import create_fork, diff_branches, effective_events
from ..analysis.analyzer import analyze_branch
from ..db import get_db
from ..events import BranchStatus
from ..models import Branch, Run
from ..schemas import (
    BranchDiff,
    BranchOut,
    BranchStats,
    BranchTimeline,
    EventOut,
    ForkRequest,
    OkResponse,
)

router = APIRouter(prefix="/api/branches", tags=["branches"])


def _get_branch(db: Session, branch_id: str) -> Branch:
    branch = db.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(404, "branch not found")
    return branch


@router.get("/{branch_id}/timeline", response_model=BranchTimeline)
def branch_timeline(branch_id: str, db: Session = Depends(get_db)) -> BranchTimeline:
    branch = _get_branch(db, branch_id)
    events = effective_events(db, branch)
    stats = BranchStats(
        branch_id=branch.id,
        events=len(events),
        tokens_in=sum(e.tokens_in for e in events),
        tokens_out=sum(e.tokens_out for e in events),
        cost_usd=round(sum(e.cost_usd for e in events), 8),
        duration_ms=round(sum(e.duration_ms for e in events), 2),
    )
    return BranchTimeline(
        branch=BranchOut.model_validate(branch),
        events=[EventOut.model_validate(e) for e in events],
        stats=stats,
    )


@router.post("/{branch_id}/fork", response_model=BranchOut, status_code=201)
async def fork_branch(
    branch_id: str, body: ForkRequest, db: Session = Depends(get_db)
) -> BranchOut:
    source = _get_branch(db, branch_id)
    if source.status in (BranchStatus.PENDING, BranchStatus.RUNNING):
        raise HTTPException(409, "cannot fork a branch that is still executing")
    run = db.get(Run, source.run_id)
    assert run is not None

    max_seq = max((e.seq for e in effective_events(db, source)), default=0)
    if body.fork_seq > max_seq + 1:
        raise HTTPException(422, f"fork_seq {body.fork_seq} is beyond the branch history ({max_seq})")

    try:
        fork, messages, parent_event_id = create_fork(db, run, source, body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    asyncio.create_task(
        execute_branch(
            run.id,
            fork.id,
            messages,
            start_seq=body.fork_seq,
            parent_event_id=parent_event_id,
        )
    )
    return BranchOut.model_validate(fork)


@router.get("/{branch_id}/diff", response_model=BranchDiff)
def branch_diff(
    branch_id: str, against: str | None = None, db: Session = Depends(get_db)
) -> BranchDiff:
    branch = _get_branch(db, branch_id)
    other_id = against or branch.parent_branch_id
    if other_id is None:
        raise HTTPException(422, "root branch has no parent to diff against; pass ?against=")
    other = _get_branch(db, other_id)
    if other.run_id != branch.run_id:
        raise HTTPException(422, "branches belong to different runs")
    return diff_branches(db, other, branch)


@router.post("/{branch_id}/analyze", response_model=OkResponse)
async def reanalyze_branch(branch_id: str, db: Session = Depends(get_db)) -> OkResponse:
    _get_branch(db, branch_id)
    await analyze_branch(branch_id)
    return OkResponse()
