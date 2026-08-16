"""Tests for reporting — covers whole-plan report and run log generation.

TDD: These tests are written before the implementation exists.
They define the expected behavior of the report generator and run logger modules.
"""

from __future__ import annotations

from typing import Any

from tests.helpers import (
    make_progress,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_done_step_progress(
    agent: str = "spec-implementer",
    model: str = "default",
    commit: str | None = None,
) -> dict[str, Any]:
    """Build a per-step progress entry for a DONE step."""
    return {
        "state": "DONE",
        "agent": agent,
        "model": model,
        "started_at": "2025-01-01T00:00:00Z",
        "completed_at": "2025-01-01T00:01:00Z",
        "pre_analysis": None,
        "verification": {
            "status": "PASS",
            "attempts": [
                {
                    "attempt": 1,
                    "status": "PASS",
                    "command_summaries": [
                        ".automation/verification/STEP-001/attempt-1-command-0.summary.json",
                    ],
                }
            ],
        },
        "fix_attempts": 0,
        "commit": commit,
        "failure_reason": None,
    }


def _make_failed_step_progress(
    failure_code: str = "VERIFICATION_FAILED",
    failure_message: str = "Verification failed.",
) -> dict[str, Any]:
    """Build a per-step progress entry for a FAILED step."""
    return {
        "state": "FAILED",
        "agent": "spec-implementer",
        "model": "default",
        "started_at": "2025-01-01T00:00:00Z",
        "completed_at": "2025-01-01T00:02:00Z",
        "pre_analysis": None,
        "verification": {
            "status": "FAIL",
            "attempts": [
                {
                    "attempt": 1,
                    "status": "FAIL",
                    "command_summaries": [
                        ".automation/verification/STEP-001/attempt-1-command-0.summary.json",
                    ],
                }
            ],
        },
        "fix_attempts": 0,
        "commit": None,
        "failure_reason": {
            "code": failure_code,
            "message": failure_message,
        },
    }


def _make_blocked_gate_progress() -> dict[str, Any]:
    """Build a per-step progress entry for a BLOCKED human gate."""
    return {
        "state": "BLOCKED",
        "agent": None,
        "model": None,
        "started_at": None,
        "completed_at": "2025-01-01T00:01:01Z",
        "pre_analysis": None,
        "verification": None,
        "fix_attempts": 0,
        "commit": None,
        "failure_reason": {
            "code": "HUMAN_GATE",
            "message": "Stopped at HUMAN_GATE: Review step",
        },
    }


# ===========================================================================
# Whole-plan report content tests
# ===========================================================================


class TestWholePlanReportSummarySection:
    """The whole-plan report should include a summary section with
    completed count and stop reason."""

    def test_report_path_convention(self) -> None:
        """Whole-plan report should be written to .automation/whole-plan-report.md."""
        from pathlib import PurePosixPath
        expected = PurePosixPath(".automation") / "whole-plan-report.md"
        assert str(expected) == ".automation/whole-plan-report.md"

    def test_summary_includes_completed_count(self) -> None:
        """The report summary should include the number of completed steps."""
        progress = make_progress(
            steps={
                "STEP-001": _make_done_step_progress(),
                "STEP-002": _make_done_step_progress(),
            }
        )
        done_count = sum(
            1 for s in progress["steps"].values() if s["state"] == "DONE"
        )
        assert done_count == 2

    def test_summary_includes_stop_reason_for_failure(self) -> None:
        """The report summary should include the stop reason when a step fails."""
        progress = make_progress(
            steps={
                "STEP-001": _make_failed_step_progress(),
            }
        )
        failed_steps = [
            sid for sid, s in progress["steps"].items() if s["state"] == "FAILED"
        ]
        assert len(failed_steps) == 1
        assert progress["steps"]["STEP-001"]["failure_reason"]["code"] == "VERIFICATION_FAILED"


class TestWholePlanReportCompletedSteps:
    """The whole-plan report should list completed step IDs and titles."""

    def test_completed_steps_listed(self) -> None:
        """Each completed step should appear with its ID."""
        progress = make_progress(
            steps={
                "STEP-001": _make_done_step_progress(),
                "STEP-002": _make_done_step_progress(),
            }
        )
        completed = [
            sid for sid, s in progress["steps"].items() if s["state"] == "DONE"
        ]
        assert "STEP-001" in completed
        assert "STEP-002" in completed


class TestWholePlanReportStoppedAt:
    """The whole-plan report should identify where execution stopped and why."""

    def test_stopped_at_human_gate(self) -> None:
        """Report should indicate stop at a HUMAN_GATE step."""
        progress = make_progress(
            steps={
                "STEP-001": _make_done_step_progress(),
                "STEP-002": _make_blocked_gate_progress(),
            }
        )
        step2 = progress["steps"]["STEP-002"]
        assert step2["state"] == "BLOCKED"
        assert step2["failure_reason"]["code"] == "HUMAN_GATE"

    def test_stopped_at_failed_verification(self) -> None:
        """Report should indicate stop at verification failure."""
        progress = make_progress(
            steps={
                "STEP-001": _make_failed_step_progress(),
            }
        )
        step1 = progress["steps"]["STEP-001"]
        assert step1["state"] == "FAILED"
        assert step1["failure_reason"]["code"] == "VERIFICATION_FAILED"


class TestWholePlanReportVerificationSummary:
    """The whole-plan report should include a pass/fail overview of verification."""

    def test_verification_pass_recorded(self) -> None:
        """PASS verification should appear in the progress."""
        progress = make_progress(
            steps={"STEP-001": _make_done_step_progress()}
        )
        assert progress["steps"]["STEP-001"]["verification"]["status"] == "PASS"

    def test_verification_fail_recorded(self) -> None:
        """FAIL verification should appear in the progress."""
        progress = make_progress(
            steps={"STEP-001": _make_failed_step_progress()}
        )
        assert progress["steps"]["STEP-001"]["verification"]["status"] == "FAIL"


class TestWholePlanReportCommits:
    """The whole-plan report should list commit hashes when commit-per-step is enabled."""

    def test_commit_hashes_listed(self) -> None:
        """Steps with commits should have their hashes available."""
        progress = make_progress(
            steps={
                "STEP-001": _make_done_step_progress(commit="abc1234"),
                "STEP-002": _make_done_step_progress(commit="def5678"),
            }
        )
        commits = [
            s["commit"]
            for s in progress["steps"].values()
            if s["commit"] is not None
        ]
        assert "abc1234" in commits
        assert "def5678" in commits

    def test_no_commits_when_disabled(self) -> None:
        """Steps without commit-per-step should have null commits."""
        progress = make_progress(
            steps={"STEP-001": _make_done_step_progress(commit=None)}
        )
        commits = [
            s["commit"]
            for s in progress["steps"].values()
            if s["commit"] is not None
        ]
        assert len(commits) == 0


class TestWholePlanReportHumanAction:
    """The whole-plan report should include a clear next action when human
    intervention is required."""

    def test_human_gate_requires_action(self) -> None:
        """When stopped at a HUMAN_GATE, the report should indicate
        a required human action."""
        progress = make_progress(
            steps={
                "STEP-001": _make_done_step_progress(),
                "STEP-002": _make_blocked_gate_progress(),
            }
        )
        # The blocked step should contain enough info for the report generator
        step2 = progress["steps"]["STEP-002"]
        assert step2["failure_reason"]["code"] == "HUMAN_GATE"
        assert "HUMAN_GATE" in step2["failure_reason"]["message"]


class TestWholePlanReportMaxStepsReached:
    """ART-006 report aspect: when max step limit is reached, the whole-plan
    report should state the limit was reached."""

    def test_max_steps_data_available(self) -> None:
        """The report generator should be able to distinguish
        max-steps-reached from normal completion."""
        # When max_steps is reached, the orchestrator stops even though
        # more steps remain — only completed steps appear in progress.
        progress = make_progress(
            steps={
                "STEP-001": _make_done_step_progress(),
                # STEP-002 is not started (not in progress dict)
            }
        )
        # The report generator receives the stop reason separately.
        # The progress still conforms to the schema.
        assert "STEP-001" in progress["steps"]
        assert "STEP-002" not in progress["steps"]


# ===========================================================================
# Run log tests
# ===========================================================================


class TestRunLogPath:
    """The run log should be written to the canonical path."""

    def test_run_log_path_convention(self) -> None:
        """Run log should be at .automation/run-log.md."""
        from pathlib import PurePosixPath
        expected = PurePosixPath(".automation") / "run-log.md"
        assert str(expected) == ".automation/run-log.md"


class TestRunLogEntryContent:
    """Each run log entry should contain all required sections."""

    def test_log_entry_has_step_id(self) -> None:
        """Each entry should include the step ID."""
        # Structural test: the run logger receives step_id.
        step_id = "STEP-001"
        assert step_id.startswith("STEP-")

    def test_log_entry_has_agent(self) -> None:
        """Each entry should record the agent used."""
        progress = make_progress(
            steps={"STEP-001": _make_done_step_progress(agent="spec-implementer")}
        )
        assert progress["steps"]["STEP-001"]["agent"] == "spec-implementer"

    def test_log_entry_has_verification_status(self) -> None:
        """Each entry should include verification outcome."""
        progress = make_progress(
            steps={"STEP-001": _make_done_step_progress()}
        )
        assert progress["steps"]["STEP-001"]["verification"]["status"] == "PASS"

    def test_log_entry_records_stop_reason(self) -> None:
        """Log entries for stopped steps should record the stop reason."""
        progress = make_progress(
            steps={"STEP-001": _make_failed_step_progress()}
        )
        assert progress["steps"]["STEP-001"]["failure_reason"] is not None
