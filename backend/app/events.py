"""Event vocabulary for the flight recorder.

The schema is OpenTelemetry-inspired: every event belongs to a trace (the run),
carries a span id, a monotonically increasing sequence number within its branch,
and a causal parent event id. Events are append-only and never mutated.
"""

from enum import StrEnum


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    LLM_MESSAGE = "llm_message"          # assistant text (thinking-out-loud / answer)
    REASONING = "reasoning"              # reasoning placeholder emitted by the model
    TOOL_CALL = "tool_call"              # agent decided to invoke a tool
    TOOL_RESULT = "tool_result"          # tool output (cached or fresh)
    RETRY = "retry"                      # a failed step being retried
    ERROR = "error"                      # unrecoverable step failure
    COMPLETION = "completion"            # final answer, terminates the branch
    REPLAY_MISS = "replay_miss"          # honest stop: no recorded execution covers this state


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class BranchStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class BranchLabel(StrEnum):
    """AI-assigned verdict for a finished branch."""

    SUCCESS = "success"
    HALLUCINATION = "hallucination"
    LOOP = "loop"
    FAILED = "failed"
    UNRECORDED = "unrecorded"  # replay left recorded coverage; nothing was fabricated
    UNLABELED = "unlabeled"


#: Event types that carry LLM token usage.
TOKEN_BEARING = {EventType.LLM_MESSAGE, EventType.REASONING, EventType.COMPLETION}
