"""Pydantic API schemas. These are the typed contract mirrored by the frontend."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .events import BranchLabel, BranchStatus, EventType, RunStatus

# ---------------------------------------------------------------- events


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    branch_id: str
    seq: int
    parent_event_id: str | None
    trace_id: str
    span_id: str
    type: EventType
    name: str
    ts: datetime
    duration_ms: float
    payload: dict
    tokens_in: int
    tokens_out: int
    cost_usd: float
    meta: dict


# ---------------------------------------------------------------- branches


class BranchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    name: str
    parent_branch_id: str | None
    fork_seq: int | None
    overrides: dict
    status: BranchStatus
    label: BranchLabel
    diagnosis: str | None
    color_index: int
    created_at: datetime


class BranchStats(BaseModel):
    branch_id: str
    events: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    duration_ms: float


class BranchTimeline(BaseModel):
    """A branch plus its fully resolved (inherited + own) event history."""

    branch: BranchOut
    events: list[EventOut]
    stats: BranchStats


# ---------------------------------------------------------------- runs


class RunCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    title: str | None = Field(default=None, max_length=200)
    seed: int = 42


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    prompt: str
    model: str
    seed: int
    status: RunStatus
    summary: str | None
    created_at: datetime


class RunDetail(RunOut):
    branches: list[BranchOut]


# ---------------------------------------------------------------- fork / replay


class ForkRequest(BaseModel):
    """Fork a branch at `fork_seq` and replay from there."""

    fork_seq: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=120)
    edited_prompt: str | None = Field(default=None, max_length=8000)
    # Map of parent event id (a tool_result event) -> replacement output payload.
    tool_overrides: dict[str, dict] = Field(default_factory=dict)


# ---------------------------------------------------------------- diff


class DiffEntry(BaseModel):
    kind: str  # "same" | "changed" | "added_a" | "added_b"
    a: EventOut | None = None
    b: EventOut | None = None


class BranchDiff(BaseModel):
    branch_a: str
    branch_b: str
    fork_seq: int | None
    entries: list[DiffEntry]


# ---------------------------------------------------------------- analysis


class AnalysisResult(BaseModel):
    branch_id: str
    label: BranchLabel
    diagnosis: str


class RunSummaryResult(BaseModel):
    run_id: str
    summary: str


# ---------------------------------------------------------------- export


class RunExport(BaseModel):
    version: int = 1
    run: RunOut
    branches: list[BranchOut]
    events: list[EventOut]


class OkResponse(BaseModel):
    ok: bool = True
