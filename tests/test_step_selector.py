"""Tests for step selection — covers SEL-001 through SEL-006.

TDD: These tests are written before the implementation exists.
They define the expected behavior of the step selector module.
"""

from __future__ import annotations

from tools.plan_parser import parse_plan
from tests.helpers import (
    make_analysis_step,
    make_human_gate_step,
    make_implementation_step,
    make_plan,
)
from tools.orchestrator.step_selector import select_next_step


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_plan(plan_text: str):
    """Parse a plan and return the list of parsed steps."""
    result = parse_plan(plan_text)
    assert result.ok, f"Plan parse errors: {result.errors}"
    return result.steps


# ---------------------------------------------------------------------------
# SEL-001: Empty progress, first step is IMPLEMENTATION → select STEP-001
# ---------------------------------------------------------------------------


class TestSEL001EmptyProgressSelectsFirstStep:
    """When no progress exists, the selector should pick the first step."""

    def test_selects_first_implementation_step(self) -> None:
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="First step"),
            make_implementation_step(step_id="STEP-002", title="Second step"),
        )
        steps = _parse_plan(plan)
        progress: dict = {}

        selection = select_next_step(steps, progress)

        assert selection is not None
        assert selection.step_id == "STEP-001"
        assert selection.action == "run"

    def test_selects_first_step_when_progress_is_empty_dict(self) -> None:
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="Only step"),
        )
        steps = _parse_plan(plan)
        progress: dict = {}

        selection = select_next_step(steps, progress)

        assert selection is not None
        assert selection.step_id == "STEP-001"


# ---------------------------------------------------------------------------
# SEL-002: STEP-001 done, no entry for STEP-002 → select STEP-002
# ---------------------------------------------------------------------------


class TestSEL002SkipsDoneSelectsNext:
    """When earlier steps are DONE, the selector picks the first incomplete."""

    def test_selects_second_step_when_first_is_done(self) -> None:
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="First step"),
            make_implementation_step(step_id="STEP-002", title="Second step"),
        )
        steps = _parse_plan(plan)
        progress = {"STEP-001": {"state": "DONE"}}

        selection = select_next_step(steps, progress)

        assert selection is not None
        assert selection.step_id == "STEP-002"
        assert selection.action == "run"

    def test_selects_third_step_when_first_two_are_done(self) -> None:
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="First step"),
            make_implementation_step(step_id="STEP-002", title="Second step"),
            make_implementation_step(step_id="STEP-003", title="Third step"),
        )
        steps = _parse_plan(plan)
        progress = {
            "STEP-001": {"state": "DONE"},
            "STEP-002": {"state": "DONE"},
        }

        selection = select_next_step(steps, progress)

        assert selection is not None
        assert selection.step_id == "STEP-003"

    def test_returns_none_when_all_steps_done(self) -> None:
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="Only step"),
        )
        steps = _parse_plan(plan)
        progress = {"STEP-001": {"state": "DONE"}}

        selection = select_next_step(steps, progress)

        assert selection is None


# ---------------------------------------------------------------------------
# SEL-003: First incomplete step is HUMAN_GATE → stop at gate
# ---------------------------------------------------------------------------


class TestSEL003StopsAtHumanGate:
    """When the first incomplete step is HUMAN_GATE, the selector stops."""

    def test_stops_at_human_gate(self) -> None:
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="First step"),
            make_human_gate_step(step_id="STEP-002", title="Review step"),
        )
        steps = _parse_plan(plan)
        progress = {"STEP-001": {"state": "DONE"}}

        selection = select_next_step(steps, progress)

        assert selection is not None
        assert selection.step_id == "STEP-002"
        assert selection.action == "stop_human_gate"

    def test_stops_at_first_step_if_gate(self) -> None:
        plan = make_plan(
            make_human_gate_step(step_id="STEP-001", title="Review first"),
            make_implementation_step(step_id="STEP-002", title="Second step"),
        )
        steps = _parse_plan(plan)
        progress: dict = {}

        selection = select_next_step(steps, progress)

        assert selection is not None
        assert selection.step_id == "STEP-001"
        assert selection.action == "stop_human_gate"


# ---------------------------------------------------------------------------
# SEL-004: First incomplete step is BLOCKED → stop
# ---------------------------------------------------------------------------


class TestSEL004StopsOnBlocked:
    """When the first incomplete step is BLOCKED, the selector stops."""

    def test_stops_on_blocked_step(self) -> None:
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="First step"),
            make_implementation_step(step_id="STEP-002", title="Second step"),
        )
        steps = _parse_plan(plan)
        progress = {
            "STEP-001": {"state": "DONE"},
            "STEP-002": {"state": "BLOCKED"},
        }

        selection = select_next_step(steps, progress)

        assert selection is not None
        assert selection.step_id == "STEP-002"
        assert selection.action == "stop_blocked"

    def test_stops_on_blocked_first_step(self) -> None:
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="First step"),
        )
        steps = _parse_plan(plan)
        progress = {"STEP-001": {"state": "BLOCKED"}}

        selection = select_next_step(steps, progress)

        assert selection is not None
        assert selection.step_id == "STEP-001"
        assert selection.action == "stop_blocked"


# ---------------------------------------------------------------------------
# SEL-005: Current step FAILED, later step otherwise runnable → stop
# ---------------------------------------------------------------------------


class TestSEL005StopsOnFailed:
    """When the current step is FAILED, execution stops — no scan-ahead."""

    def test_stops_on_failed_step_does_not_skip(self) -> None:
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="First step"),
            make_implementation_step(step_id="STEP-002", title="Second step"),
        )
        steps = _parse_plan(plan)
        progress = {"STEP-001": {"state": "FAILED"}}

        selection = select_next_step(steps, progress)

        assert selection is not None
        assert selection.step_id == "STEP-001"
        assert selection.action == "stop_failed"

    def test_does_not_scan_ahead_past_failed(self) -> None:
        """Even though STEP-002 has no progress (TODO), STEP-001 is FAILED
        so the selector must not skip to STEP-002."""
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="First step"),
            make_implementation_step(step_id="STEP-002", title="Second step"),
            make_implementation_step(step_id="STEP-003", title="Third step"),
        )
        steps = _parse_plan(plan)
        progress = {"STEP-001": {"state": "FAILED"}}

        selection = select_next_step(steps, progress)

        assert selection is not None
        assert selection.step_id == "STEP-001"
        assert selection.action == "stop_failed"


# ---------------------------------------------------------------------------
# SEL-006: Step marked SKIPPED by human → continue to next step
# ---------------------------------------------------------------------------


class TestSEL006SkippedStepContinues:
    """A SKIPPED step is treated as complete — selector moves past it."""

    def test_skips_over_skipped_step(self) -> None:
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="First step"),
            make_implementation_step(step_id="STEP-002", title="Second step"),
        )
        steps = _parse_plan(plan)
        progress = {"STEP-001": {"state": "SKIPPED"}}

        selection = select_next_step(steps, progress)

        assert selection is not None
        assert selection.step_id == "STEP-002"
        assert selection.action == "run"


class TestAnalysisStepSelection:
    """ANALYSIS steps participate in strict document-order selection."""

    def test_selects_analysis_step_after_completed_prior_step(self) -> None:
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="First step"),
            make_analysis_step(step_id="STEP-002", title="Analyze coverage"),
            make_implementation_step(step_id="STEP-003", title="Follow-up step"),
        )
        steps = _parse_plan(plan)
        progress = {"STEP-001": {"state": "DONE"}}

        selection = select_next_step(steps, progress)

        assert selection is not None
        assert selection.step_id == "STEP-002"
        assert selection.action == "run"

    def test_completed_analysis_step_allows_next_step(self) -> None:
        plan = make_plan(
            make_analysis_step(step_id="STEP-001", title="Analyze coverage"),
            make_implementation_step(step_id="STEP-002", title="Follow-up step"),
        )
        steps = _parse_plan(plan)
        progress = {"STEP-001": {"state": "DONE"}}

        selection = select_next_step(steps, progress)

        assert selection is not None
        assert selection.step_id == "STEP-002"
        assert selection.action == "run"


class TestStepOutcomePolicy:
    """One outcome enum should drive state, stop reason, and exit code."""

    def test_outcome_policy_maps_human_gate_blocked_and_failed(self) -> None:
        from tools.orchestrator.outcomes import STEP_OUTCOME_POLICY, StepOutcome

        assert STEP_OUTCOME_POLICY[StepOutcome.HUMAN_GATE].state == "BLOCKED"
        assert STEP_OUTCOME_POLICY[StepOutcome.HUMAN_GATE].stop_reason == "HUMAN_GATE"
        assert STEP_OUTCOME_POLICY[StepOutcome.HUMAN_GATE].exit_code == 0

        assert STEP_OUTCOME_POLICY[StepOutcome.AGENT_BLOCKED].state == "BLOCKED"
        assert STEP_OUTCOME_POLICY[StepOutcome.AGENT_BLOCKED].stop_reason == "AGENT_BLOCKED"
        assert STEP_OUTCOME_POLICY[StepOutcome.AGENT_BLOCKED].exit_code == 1

        assert STEP_OUTCOME_POLICY[StepOutcome.AGENT_FAILED].state == "FAILED"
        assert STEP_OUTCOME_POLICY[StepOutcome.AGENT_FAILED].stop_reason == "FAILED"
        assert STEP_OUTCOME_POLICY[StepOutcome.AGENT_FAILED].exit_code == 1

    def test_outcome_policy_covers_known_stop_conditions(self) -> None:
        from tools.orchestrator.outcomes import STEP_OUTCOME_POLICY, StepOutcome

        expected = {
            StepOutcome.HUMAN_GATE,
            StepOutcome.AGENT_BLOCKED,
            StepOutcome.AGENT_FAILED,
            StepOutcome.INVALID_AGENT_RESULT,
            StepOutcome.SCOPE_VIOLATION,
            StepOutcome.DIRTY_WORKTREE,
            StepOutcome.PRE_ANALYSIS_FAILED,
            StepOutcome.VERIFICATION_FAILED,
            StepOutcome.VERIFICATION_ERROR,
        }

        assert expected.issubset(STEP_OUTCOME_POLICY.keys())

        assert STEP_OUTCOME_POLICY[StepOutcome.VERIFICATION_ERROR].state == "BLOCKED"
        assert STEP_OUTCOME_POLICY[StepOutcome.VERIFICATION_ERROR].stop_reason == "BLOCKED"

    def test_skips_multiple_skipped_steps(self) -> None:
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="First step"),
            make_implementation_step(step_id="STEP-002", title="Second step"),
            make_implementation_step(step_id="STEP-003", title="Third step"),
        )
        steps = _parse_plan(plan)
        progress = {
            "STEP-001": {"state": "SKIPPED"},
            "STEP-002": {"state": "SKIPPED"},
        }

        selection = select_next_step(steps, progress)

        assert selection is not None
        assert selection.step_id == "STEP-003"
        assert selection.action == "run"

    def test_all_skipped_returns_none(self) -> None:
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="Only step"),
        )
        steps = _parse_plan(plan)
        progress = {"STEP-001": {"state": "SKIPPED"}}

        selection = select_next_step(steps, progress)

        assert selection is None

    def test_skipped_then_human_gate(self) -> None:
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="First step"),
            make_human_gate_step(step_id="STEP-002", title="Review step"),
        )
        steps = _parse_plan(plan)
        progress = {"STEP-001": {"state": "SKIPPED"}}

        selection = select_next_step(steps, progress)

        assert selection is not None
        assert selection.step_id == "STEP-002"
        assert selection.action == "stop_human_gate"


# ---------------------------------------------------------------------------
# SEL-MINOR: Minor step ID selection (STEP-NNN.NNN)
# ---------------------------------------------------------------------------


class TestMinorStepIDSelection:
    """Tests for step selection with minor (sub-step) IDs."""

    def test_major_selected_before_its_minor(self) -> None:
        """STEP-002 is selected before STEP-002.001."""
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="First step"),
            make_implementation_step(step_id="STEP-002", title="Second step"),
            make_human_gate_step(step_id="STEP-002.001", title="Sub-step one"),
            make_human_gate_step(step_id="STEP-002.002", title="Sub-step two"),
        )
        steps = _parse_plan(plan)
        progress = {"STEP-001": {"state": "DONE"}}

        selection = select_next_step(steps, progress)

        assert selection is not None
        assert selection.step_id == "STEP-002"
        assert selection.action == "run"

    def test_completed_major_and_first_minor_selects_second_minor(self) -> None:
        """With STEP-002 and STEP-002.001 done, proceeds to STEP-002.002."""
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="First step"),
            make_implementation_step(step_id="STEP-002", title="Second step"),
            make_implementation_step(step_id="STEP-002.001", title="Sub one"),
            make_implementation_step(step_id="STEP-002.002", title="Sub two"),
            make_implementation_step(step_id="STEP-003", title="Third step"),
        )
        steps = _parse_plan(plan)
        progress = {
            "STEP-001": {"state": "DONE"},
            "STEP-002": {"state": "DONE"},
            "STEP-002.001": {"state": "DONE"},
        }

        selection = select_next_step(steps, progress)

        assert selection is not None
        assert selection.step_id == "STEP-002.002"
        assert selection.action == "run"

    def test_all_minor_done_proceeds_to_next_major(self) -> None:
        """With all minors complete, selection moves to the next major step."""
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="First step"),
            make_implementation_step(step_id="STEP-001.001", title="Sub one"),
            make_implementation_step(step_id="STEP-002", title="Second step"),
        )
        steps = _parse_plan(plan)
        progress = {
            "STEP-001": {"state": "DONE"},
            "STEP-001.001": {"state": "DONE"},
        }

        selection = select_next_step(steps, progress)

        assert selection is not None
        assert selection.step_id == "STEP-002"
        assert selection.action == "run"
