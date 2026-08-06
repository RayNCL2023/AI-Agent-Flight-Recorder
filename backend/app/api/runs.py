"""Run lifecycle: create/list/get/delete, plus trace export/import."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agent.engine import execute_branch
from ..agent.llm import model_name
from ..agent.replay import initial_messages
from ..config import get_settings
from ..db import get_db
from ..events import BranchStatus, RunStatus
from ..models import Branch, Event, Run
from ..schemas import (
    BranchOut,
    EventOut,
    OkResponse,
    RunCreate,
    RunDetail,
    RunExport,
    RunOut,
)

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post("", response_model=RunDetail, status_code=201)
async def create_run(body: RunCreate, db: Session = Depends(get_db)) -> RunDetail:
    settings = get_settings()
    run = Run(
        title=body.title or body.prompt[:60],
        prompt=body.prompt,
        model=model_name(settings),
        seed=body.seed,
        status=RunStatus.PENDING,
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


@router.get("", response_model=list[RunOut])
def list_runs(db: Session = Depends(get_db)) -> list[Run]:
    return list(db.scalars(select(Run).order_by(Run.created_at.desc())))


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
    return RunExport(
        run=RunOut.model_validate(run),
        branches=[BranchOut.model_validate(b) for b in run.branches],
        events=[EventOut.model_validate(e) for e in events],
    )


@router.post("/import", response_model=RunDetail, status_code=201)
def import_run(payload: RunExport, db: Session = Depends(get_db)) -> RunDetail:
    if db.get(Run, payload.run.id) is not None:
        raise HTTPException(409, "a run with this id already exists")
    run = Run(**payload.run.model_dump())
    db.add(run)
    for b in payload.branches:
        db.add(Branch(**b.model_dump()))
    for e in payload.events:
        db.add(Event(**e.model_dump()))
    db.commit()
    db.refresh(run)
    return _detail(run)


def _detail(run: Run) -> RunDetail:
    return RunDetail(
        **RunOut.model_validate(run).model_dump(),
        branches=[BranchOut.model_validate(b) for b in run.branches],
    )
