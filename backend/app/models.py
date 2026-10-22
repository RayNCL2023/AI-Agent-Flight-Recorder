"""ORM models: an immutable, fork-aware event log.

Forks are zero-copy: a Branch references its parent branch and the sequence
number it forked from. A branch's *effective history* is resolved by walking the
ancestor chain (see agent/replay.py) — events are never duplicated or mutated.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .events import BranchLabel, BranchStatus, EventType, RunStatus


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Run(Base):
    """A single top-level agent execution (one trace)."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(100))
    seed: Mapped[int] = mapped_column(Integer, default=42)
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.PENDING)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "recorded" = immutable library trace shipped with the app; "live" = a run
    # a user executed in live mode.
    source: Mapped[str] = mapped_column(String(20), default="live")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tools_used: Mapped[list] = mapped_column(JSON, default=list)
    # Curated fork variants recorded alongside the trace:
    #   [{id, title, description, fork_seq, edited_prompt, tool_overrides,
    #     recorded_label, recorded_diagnosis}]
    experiments: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    branches: Mapped[list["Branch"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class Branch(Base):
    """One timeline lane. The root branch has no parent; forks reference theirs."""

    __tablename__ = "branches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    parent_branch_id: Mapped[str | None] = mapped_column(
        ForeignKey("branches.id"), nullable=True
    )
    # Events with seq < fork_seq are inherited from the parent branch.
    fork_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # User edits applied at fork time:
    #   {"edited_prompt": str | None, "tool_overrides": {parent_event_id: output}}
    overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default=BranchStatus.PENDING)
    label: Mapped[str] = mapped_column(String(20), default=BranchLabel.UNLABELED)
    diagnosis: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Provenance of label/diagnosis: "recorded" | "heuristic" | "llm".
    analysis_source: Mapped[str] = mapped_column(String(20), default="heuristic")
    color_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    run: Mapped[Run] = relationship(back_populates="branches")
    events: Mapped[list["Event"]] = relationship(
        back_populates="branch",
        cascade="all, delete-orphan",
        order_by="Event.seq",
        foreign_keys="Event.branch_id",
    )


class Event(Base):
    """Append-only execution record. Rows are written once and never updated."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_branch_seq", "branch_id", "seq", unique=True),
        Index("ix_events_run", "run_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    branch_id: Mapped[str] = mapped_column(
        ForeignKey("branches.id", ondelete="CASCADE")
    )
    seq: Mapped[int] = mapped_column(Integer)
    parent_event_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(32))  # == run_id, OTel-style alias
    span_id: Mapped[str] = mapped_column(String(32), default=_uuid)
    type: Mapped[str] = mapped_column(String(30))  # EventType
    name: Mapped[str] = mapped_column(String(120))
    ts: Mapped[datetime] = mapped_column(default=utcnow)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    branch: Mapped[Branch] = relationship(
        back_populates="events", foreign_keys=[branch_id]
    )

    @property
    def event_type(self) -> EventType:
        return EventType(self.type)


class LLMCacheEntry(Base):
    """Deterministic-replay cache for LLM completions.

    Keyed by a hash of the full conversation state (model + seed + messages), so
    replaying any recorded path — including recorded fork variants — resolves
    each LLM step from the recording instead of calling a model. A state with no
    entry is a *replay miss*: the honest "no recorded execution" stop.
    """

    __tablename__ = "llm_cache"
    __table_args__ = (
        Index("ix_llm_cache_key", "run_id", "cache_key", unique=True),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    cache_key: Mapped[str] = mapped_column(String(64))  # sha256(model + seed + messages)
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ToolCacheEntry(Base):
    """Deterministic-replay cache: first live tool result per (run, tool, args)."""

    __tablename__ = "tool_cache"
    __table_args__ = (
        Index("ix_tool_cache_key", "run_id", "cache_key", unique=True),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    cache_key: Mapped[str] = mapped_column(String(64))  # sha256(tool + canonical args)
    tool: Mapped[str] = mapped_column(String(60))
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
