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
    analysis_source: str  # "recorded" | "heuristic" | "llm"
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


class ExperimentOut(BaseModel):
    """A curated fork variant recorded alongside a library trace."""

    id: str
    title: str
    description: str
    fork_seq: int
    edited_prompt: str | None = None
    tool_overrides: dict[str, dict] = Field(default_factory=dict)
    recorded_label: BranchLabel = BranchLabel.UNLABELED
    recorded_diagnosis: str | None = None


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    prompt: str
    model: str
    seed: int
    status: RunStatus
    summary: str | None
    source: str  # "recorded" | "live"
    description: str | None
    tools_used: list[str]
    experiments: list[ExperimentOut]
    created_at: datetime


class RunStats(BaseModel):
    events: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0


class RunListItem(RunOut):
    """Library card: a run plus aggregate stats over its stored events."""

    stats: RunStats


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


class ToolCacheOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cache_key: str
    tool: str
    args: dict
    output: dict


class LLMCacheOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cache_key: str
    response: dict


class RunExport(BaseModel):
    """Complete portable trace bundle.

    Version 2 carries both replay caches so an imported trace replays (and
    forks) deterministically. Version 1 bundles import with empty caches: their
    events remain inspectable but forks stop with an honest replay_miss.
    """

    version: int = 2
    run: RunOut
    branches: list[BranchOut]
    events: list[EventOut]
    tool_cache: list[ToolCacheOut] = Field(default_factory=list)
    llm_cache: list[LLMCacheOut] = Field(default_factory=list)


class OkResponse(BaseModel):
    ok: bool = True
