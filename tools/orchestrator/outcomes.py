"""Step outcome policy mapping for run-loop stop handling."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from tools.constants import (
    STATE_BLOCKED,
    STATE_FAILED,
    STOP_AGENT_BLOCKED,
    STOP_BLOCKED,
    STOP_DIRTY_WORKTREE,
    STOP_FAILED,
    STOP_HUMAN_GATE,
    STOP_INVALID_AGENT_RESULT,
    STOP_PRE_ANALYSIS_FAILED,
    STOP_SCOPE_VIOLATION,
    STOP_VERIFICATION_FAILED,
)


class StepOutcome(Enum):
    """Canonical step stop outcomes."""

    HUMAN_GATE = "HUMAN_GATE"
    AGENT_BLOCKED = "AGENT_BLOCKED"
    AGENT_FAILED = "AGENT_FAILED"
    INVALID_AGENT_RESULT = "INVALID_AGENT_RESULT"
    SCOPE_VIOLATION = "SCOPE_VIOLATION"
    DIRTY_WORKTREE = "DIRTY_WORKTREE"
    PRE_ANALYSIS_FAILED = "PRE_ANALYSIS_FAILED"
    PRE_ANALYSIS_ERROR = "PRE_ANALYSIS_ERROR"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    VERIFICATION_ERROR = "VERIFICATION_ERROR"


@dataclass(frozen=True)
class StepOutcomePolicy:
    """State, stop reason, and exit code for one canonical outcome."""

    state: str
    stop_reason: str
    exit_code: int


STEP_OUTCOME_POLICY: dict[StepOutcome, StepOutcomePolicy] = {
    StepOutcome.HUMAN_GATE: StepOutcomePolicy(STATE_BLOCKED, STOP_HUMAN_GATE, 0),
    StepOutcome.AGENT_BLOCKED: StepOutcomePolicy(STATE_BLOCKED, STOP_AGENT_BLOCKED, 1),
    StepOutcome.AGENT_FAILED: StepOutcomePolicy(STATE_FAILED, STOP_FAILED, 1),
    StepOutcome.INVALID_AGENT_RESULT: StepOutcomePolicy(STATE_FAILED, STOP_INVALID_AGENT_RESULT, 1),
    StepOutcome.SCOPE_VIOLATION: StepOutcomePolicy(STATE_FAILED, STOP_SCOPE_VIOLATION, 1),
    StepOutcome.DIRTY_WORKTREE: StepOutcomePolicy(STATE_BLOCKED, STOP_DIRTY_WORKTREE, 1),
    StepOutcome.PRE_ANALYSIS_FAILED: StepOutcomePolicy(STATE_FAILED, STOP_PRE_ANALYSIS_FAILED, 1),
    StepOutcome.PRE_ANALYSIS_ERROR: StepOutcomePolicy(STATE_BLOCKED, STOP_BLOCKED, 1),
    StepOutcome.VERIFICATION_FAILED: StepOutcomePolicy(STATE_FAILED, STOP_VERIFICATION_FAILED, 1),
    StepOutcome.VERIFICATION_ERROR: StepOutcomePolicy(STATE_BLOCKED, STOP_BLOCKED, 1),
}