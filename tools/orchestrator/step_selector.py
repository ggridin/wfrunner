"""Step selector — selects the next step to execute in strict document order."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.constants import (
    FIELD_ID,
    FIELD_TYPE,
    STATE_DONE,
    STATE_SKIPPED,
    STATE_FAILED,
    STATE_BLOCKED,
    STEP_TYPE_IMPLEMENTATION,
    STEP_TYPE_HUMAN_GATE,
)
from tools.plan_parser import ParsedStep


@dataclass
class StepSelection:
    """Result of step selection.

    Attributes:
        step_id: The ID of the selected step.
        step_index: The index of the selected step in the plan.
        action: One of "run", "stop_human_gate", "stop_blocked", "stop_failed".
    """

    step_id: str
    step_index: int
    action: str  # "run", "stop_human_gate", "stop_blocked", "stop_failed"


def select_next_step(
    steps: list[ParsedStep],
    progress: dict[str, Any],
) -> StepSelection | None:
    """Select the next step to execute based on plan order and progress state.

    Args:
        steps: Parsed steps in document order.
        progress: Per-step progress dict keyed by step ID.
            Each value should contain at least a ``state`` key.

    Returns:
        A StepSelection indicating which step to act on and what action,
        or None if all steps are complete.
    """
    _TERMINAL_STATES = {STATE_DONE, STATE_SKIPPED}

    for index, step in enumerate(steps):
        step_id = step.yaml_block[FIELD_ID]
        step_type = step.yaml_block.get(FIELD_TYPE, STEP_TYPE_IMPLEMENTATION)
        state = progress.get(step_id, {}).get("state")

        # Completed or skipped steps are passed over.
        if state in _TERMINAL_STATES:
            continue

        # Failed step — stop immediately.
        if state == STATE_FAILED:
            return StepSelection(step_id=step_id, step_index=index, action="stop_failed")

        # Blocked step — stop immediately.
        if state == STATE_BLOCKED:
            return StepSelection(step_id=step_id, step_index=index, action="stop_blocked")

        # HUMAN_GATE type — stop for human review.
        if step_type == STEP_TYPE_HUMAN_GATE:
            return StepSelection(step_id=step_id, step_index=index, action="stop_human_gate")

        # IMPLEMENTATION step with no progress or TODO state — run it.
        return StepSelection(step_id=step_id, step_index=index, action="run")

    # All steps complete.
    return None
