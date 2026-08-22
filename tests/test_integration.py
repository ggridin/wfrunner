"""Integration tests — exercise the full orchestrator loop via run().

These tests validate the Phase 1 acceptance criteria by calling
tools.run_plan.run() with a FakeAgentAdapter and temp file system,
verifying that plan parsing, validation, step selection, agent
invocation, verification, progress persistence, and report generation
all work together correctly.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from jsonschema import Draft202012Validator

from tests.fake_agent import FakeAgentAdapter
from tests.helpers import (
    make_default_config,
    make_analysis_step,
    make_human_gate_step,
    make_implementation_step,
    make_plan,
)
from tools.orchestrator.change_detector import FakeChangeDetector
from tools.run_plan import prepare_run, run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prepare_context(
    plan_file: Path,
    automation_dir: Path,
    *,
    resume: bool = False,
) -> dict[str, Any]:
    """Prepare a run context using the test automation directory."""
    config = make_default_config(automation_dir=str(automation_dir))
    return prepare_run(str(plan_file), config, resume=resume)


def _write_plan(tmp_path: Path, *step_blocks: str) -> Path:
    """Write a plan file to tmp_path and return its path."""
    plan_text = make_plan(*step_blocks)
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(plan_text, encoding="utf-8")
    return plan_file


def _load_progress(automation_dir: Path) -> dict[str, Any]:
    """Load progress.json from the automation dir."""
    return json.loads((automation_dir / "progress.json").read_text(encoding="utf-8"))


def _load_progress_schema() -> dict[str, Any]:
    """Load the canonical progress.json schema."""
    schema_path = Path(__file__).resolve().parent.parent / "docs" / "schemas" / "progress.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _write_system_prompts(automation_dir: Path) -> None:
    """Write minimal system prompts next to the test automation directory."""
    prompts_dir = automation_dir.parent / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "system_prompt.implementation.md").write_text(
        "Implement exactly one step.\n",
        encoding="utf-8",
    )
    (prompts_dir / "system_prompt.analysis.md").write_text(
        "Analyze exactly one step.\n",
        encoding="utf-8",
    )


def _passing_verification() -> list[str]:
    """Return a verification command that always passes."""
    return ['"python -c \\"print(1)\\"\"']


def _failing_verification() -> list[str]:
    """Return a verification command that always fails."""
    return ['"python -c \\"raise SystemExit(1)\\"\"']


# ---------------------------------------------------------------------------
# Integration: Valid plan passes validation and runs
# ---------------------------------------------------------------------------

class TestValidPlanPassesValidation:
    """Acceptance: A plan with valid metadata passes validation."""

    def test_valid_plan_runs_to_completion(
        self, tmp_path: Path, fake_agent: FakeAgentAdapter
    ) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="Only step",
                verification_commands=_passing_verification(),
            ),
        )
        fake_agent.enqueue_done("STEP-001")
        automation_dir = tmp_path / ".automation"
        ctx = _prepare_context(plan_file, automation_dir)

        with (
            patch("tools.run_plan._is_worktree_clean", return_value=True),
        ):
            exit_code = run(
                ctx,
                adapter=fake_agent,
                change_detector=FakeChangeDetector({}),
            )

        assert exit_code == 0


class TestInvalidPlanFailsValidation:
    """Acceptance: Invalid metadata fails validation with useful errors."""

    def test_missing_plan_file_returns_error(self, tmp_path: Path) -> None:
        ctx = _prepare_context(tmp_path / "nonexistent.md", tmp_path / ".automation")
        exit_code = run(ctx)
        assert exit_code == 2

    def test_malformed_plan_returns_validation_error(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "bad-plan.md"
        plan_file.write_text("# Plan\n\nNo steps here.", encoding="utf-8")
        ctx = _prepare_context(plan_file, tmp_path / ".automation")
        exit_code = run(ctx)
        # Should fail at validation (no steps) or return 2.
        assert exit_code == 2


# ---------------------------------------------------------------------------
# Integration: Strict document order execution
# ---------------------------------------------------------------------------

class TestStrictDocumentOrder:
    """Acceptance: Steps execute strictly in document order."""

    def test_two_steps_run_in_order(
        self, tmp_path: Path, fake_agent: FakeAgentAdapter
    ) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="First",
                verification_commands=_passing_verification(),
            ),
            make_implementation_step(
                step_id="STEP-002",
                title="Second",
                verification_commands=_passing_verification(),
            ),
        )
        fake_agent.enqueue_done("STEP-001")
        fake_agent.enqueue_done("STEP-002")
        automation_dir = tmp_path / ".automation"
        ctx = _prepare_context(plan_file, automation_dir)

        with (
            patch("tools.run_plan._is_worktree_clean", return_value=True),
        ):
            exit_code = run(
                ctx,
                adapter=fake_agent,
                change_detector=FakeChangeDetector({}),
            )

        assert exit_code == 0
        assert len(fake_agent.invocations) == 2
        assert fake_agent.invocations[0].step_id == "STEP-001"
        assert fake_agent.invocations[1].step_id == "STEP-002"

        progress = _load_progress(automation_dir)
        assert progress["steps"]["STEP-001"]["state"] == "DONE"
        assert progress["steps"]["STEP-002"]["state"] == "DONE"


# ---------------------------------------------------------------------------
# Integration: HUMAN_GATE stops execution
# ---------------------------------------------------------------------------

class TestHumanGateStopsExecution:
    """Acceptance: HUMAN_GATE stops execution."""

    def test_stops_at_human_gate(
        self, tmp_path: Path, fake_agent: FakeAgentAdapter
    ) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="First",
                verification_commands=_passing_verification(),
            ),
            make_human_gate_step(step_id="STEP-002", title="Review"),
            make_implementation_step(
                step_id="STEP-003",
                title="Never reached",
                verification_commands=_passing_verification(),
            ),
        )
        fake_agent.enqueue_done("STEP-001")
        automation_dir = tmp_path / ".automation"
        ctx = _prepare_context(plan_file, automation_dir)

        with (
            patch("tools.run_plan._is_worktree_clean", return_value=True),
        ):
            exit_code = run(
                ctx,
                adapter=fake_agent,
                change_detector=FakeChangeDetector({}),
            )

        assert exit_code == 0  # HUMAN_GATE is a clean stop
        assert len(fake_agent.invocations) == 1

        progress = _load_progress(automation_dir)
        assert progress["steps"]["STEP-001"]["state"] == "DONE"
        assert progress["steps"]["STEP-002"]["state"] == "BLOCKED"
        assert progress["steps"]["STEP-002"]["failure_reason"]["code"] == "HUMAN_GATE"
        assert progress["steps"]["STEP-003"]["state"] == "TODO"


# ---------------------------------------------------------------------------
# Integration: Agent invoked for exactly one step at a time
# ---------------------------------------------------------------------------

class TestOneStepMode:
    """Acceptance: Agent is invoked for exactly one step at a time (--one-step)."""

    def test_one_step_executes_only_first(
        self, tmp_path: Path, fake_agent: FakeAgentAdapter
    ) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="First",
                verification_commands=_passing_verification(),
            ),
            make_implementation_step(
                step_id="STEP-002",
                title="Second",
                verification_commands=_passing_verification(),
            ),
        )
        fake_agent.enqueue_done("STEP-001")
        automation_dir = tmp_path / ".automation"
        ctx = _prepare_context(plan_file, automation_dir)

        with (
            patch("tools.run_plan._is_worktree_clean", return_value=True),
        ):
            exit_code = run(
                ctx,
                one_step=True,
                adapter=fake_agent,
                change_detector=FakeChangeDetector({}),
            )

        assert exit_code == 0
        assert len(fake_agent.invocations) == 1
        assert fake_agent.invocations[0].step_id == "STEP-001"

        progress = _load_progress(automation_dir)
        assert progress["steps"]["STEP-001"]["state"] == "DONE"
        assert progress["steps"]["STEP-002"]["state"] == "TODO"


# ---------------------------------------------------------------------------
# Integration: Verification failure stops execution
# ---------------------------------------------------------------------------

class TestVerificationFailureStops:
    """Acceptance: Verification commands are run and logged;
    failure stops execution."""

    def test_verification_failure_stops_run(
        self, tmp_path: Path, fake_agent: FakeAgentAdapter
    ) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="Failing step",
                verification_commands=_failing_verification(),
            ),
            make_implementation_step(
                step_id="STEP-002",
                title="Never reached",
                verification_commands=_passing_verification(),
            ),
        )
        fake_agent.enqueue_done("STEP-001")
        automation_dir = tmp_path / ".automation"
        ctx = _prepare_context(plan_file, automation_dir)

        with (
            patch("tools.run_plan._is_worktree_clean", return_value=True),
        ):
            exit_code = run(
                ctx,
                adapter=fake_agent,
                change_detector=FakeChangeDetector({}),
            )

        assert exit_code == 1
        assert len(fake_agent.invocations) == 1

        progress = _load_progress(automation_dir)
        assert progress["steps"]["STEP-001"]["state"] == "FAILED"
        assert progress["steps"]["STEP-001"]["failure_reason"]["code"] == "VERIFICATION_FAILED"
        assert progress["steps"]["STEP-002"]["state"] == "TODO"


# ---------------------------------------------------------------------------
# Integration: Agent BLOCKED result stops execution
# ---------------------------------------------------------------------------

class TestAgentBlockedStops:
    """Acceptance: Agent returns BLOCKED → orchestrator stops."""

    def test_blocked_agent_stops_run(
        self, tmp_path: Path, fake_agent: FakeAgentAdapter
    ) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="Blocked step",
                verification_commands=_passing_verification(),
            ),
        )
        fake_agent.enqueue_blocked("STEP-001", "Missing dependency")
        automation_dir = tmp_path / ".automation"
        ctx = _prepare_context(plan_file, automation_dir)

        with (
            patch("tools.run_plan._is_worktree_clean", return_value=True),
        ):
            exit_code = run(
                ctx,
                adapter=fake_agent,
                change_detector=FakeChangeDetector({}),
            )

        assert exit_code == 1
        progress = _load_progress(automation_dir)
        assert progress["steps"]["STEP-001"]["state"] == "BLOCKED"


# ---------------------------------------------------------------------------
# Integration: Post-agent scope enforcement
# ---------------------------------------------------------------------------

class TestPostAgentScopeEnforcement:
    """Acceptance: detected post-agent changes are checked against allowed_files."""

    def test_unauthorized_post_agent_change_fails_step(
        self, tmp_path: Path, fake_agent: FakeAgentAdapter
    ) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="Scoped step",
                allowed_files=["tools/allowed.py"],
                verification_commands=_passing_verification(),
            ),
            make_implementation_step(
                step_id="STEP-002",
                title="Never reached",
                verification_commands=_passing_verification(),
            ),
        )
        fake_agent.enqueue_done("STEP-001")
        change_detector = FakeChangeDetector({"tools/not_allowed.py": "modified"})
        automation_dir = tmp_path / ".automation"
        ctx = _prepare_context(plan_file, automation_dir)

        with patch("tools.run_plan._is_worktree_clean", return_value=True):
            exit_code = run(ctx, adapter=fake_agent, change_detector=change_detector)

        assert exit_code == 1
        assert len(fake_agent.invocations) == 1

        progress = _load_progress(automation_dir)
        assert progress["steps"]["STEP-001"]["state"] == "FAILED"
        assert progress["steps"]["STEP-001"]["failure_reason"]["code"] == "SCOPE_VIOLATION"
        assert progress["steps"]["STEP-002"]["state"] == "TODO"
        assert not (automation_dir / "verification" / "STEP-001").exists()

    def test_authorized_post_agent_change_proceeds_to_verification(
        self, tmp_path: Path, fake_agent: FakeAgentAdapter
    ) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="Scoped step",
                allowed_files=["tools/allowed.py"],
                verification_commands=_passing_verification(),
            ),
        )
        fake_agent.enqueue_done("STEP-001")
        change_detector = FakeChangeDetector({"tools/allowed.py": "modified"})
        automation_dir = tmp_path / ".automation"
        ctx = _prepare_context(plan_file, automation_dir)

        with patch("tools.run_plan._is_worktree_clean", return_value=True):
            exit_code = run(ctx, adapter=fake_agent, change_detector=change_detector)

        assert exit_code == 0

        progress = _load_progress(automation_dir)
        assert progress["steps"]["STEP-001"]["state"] == "DONE"
        assert progress["steps"]["STEP-001"]["verification"]["status"] == "PASS"
        assert (automation_dir / "verification" / "STEP-001" / "attempt-1-command-0.summary.json").exists()


class TestUnavailableChangeDetection:
    """Git failures block execution unless scope enforcement is explicitly disabled."""

    @pytest.mark.parametrize(
        ("git_error", "message_fragment"),
        [
            (FileNotFoundError("git"), "not found"),
            (subprocess.CalledProcessError(128, ["git", "status"]), "exit code 128"),
            (subprocess.TimeoutExpired(["git", "status"], 30), "timed out after 30 seconds"),
        ],
    )
    @pytest.mark.parametrize("step_type", ["IMPLEMENTATION", "ANALYSIS"])
    def test_git_detection_failure_blocks_step(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
        git_error: Exception,
        message_fragment: str,
        step_type: str,
    ) -> None:
        step = (
            make_implementation_step(
                step_id="STEP-001",
                title="Requires change detection",
                verification_commands=_passing_verification(),
            )
            if step_type == "IMPLEMENTATION"
            else make_analysis_step(step_id="STEP-001", title="Requires change detection")
        )
        plan_file = _write_plan(tmp_path, step)
        automation_dir = tmp_path / ".automation"
        ctx = _prepare_context(plan_file, automation_dir)

        with patch(
            "tools.run_plan._ConfiguredGitChangeDetector.detect_changes",
            side_effect=git_error,
        ):
            exit_code = run(ctx, adapter=fake_agent)

        assert exit_code == 1
        assert fake_agent.invocations == []
        step_progress = _load_progress(automation_dir)["steps"]["STEP-001"]
        assert step_progress["state"] == "BLOCKED"
        assert step_progress["failure_reason"]["code"] == "CHANGE_DETECTION_UNAVAILABLE"
        assert message_fragment in step_progress["failure_reason"]["message"]

    def test_explicit_opt_out_allows_run_to_proceed(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="Explicitly unscoped step",
                verification_commands=_passing_verification(),
            ),
        )
        fake_agent.enqueue_done("STEP-001")
        automation_dir = tmp_path / ".automation"
        ctx = _prepare_context(plan_file, automation_dir)

        with (
            patch("tools.run_plan._is_worktree_clean", return_value=True),
            patch(
                "tools.run_plan._create_default_change_detector",
                side_effect=AssertionError("change detection should be disabled"),
            ),
        ):
            exit_code = run(
                ctx,
                adapter=fake_agent,
                no_scope_enforcement=True,
            )

        assert exit_code == 0
        assert _load_progress(automation_dir)["steps"]["STEP-001"]["state"] == "DONE"


# ---------------------------------------------------------------------------
# Integration: Verification progress shape
# ---------------------------------------------------------------------------

class TestVerificationProgressShape:
    """Acceptance: verification progress matches docs/schemas/progress.schema.json."""

    def test_successful_step_writes_schema_compliant_verification_summary(
        self, tmp_path: Path, fake_agent: FakeAgentAdapter
    ) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="Step",
                verification_commands=_passing_verification(),
            ),
        )
        fake_agent.enqueue_done("STEP-001")
        automation_dir = tmp_path / ".automation"
        ctx = _prepare_context(plan_file, automation_dir)

        with patch("tools.run_plan._is_worktree_clean", return_value=True):
            exit_code = run(
                ctx,
                adapter=fake_agent,
                change_detector=FakeChangeDetector({}),
            )

        assert exit_code == 0

        progress = _load_progress(automation_dir)
        summary_path = automation_dir / "verification" / "STEP-001" / "attempt-1-command-0.summary.json"
        assert progress["steps"]["STEP-001"]["verification"] == {
            "status": "PASS",
            "attempts": [
                {
                    "attempt": 1,
                    "status": "PASS",
                    "command_summaries": [str(summary_path)],
                }
            ],
        }
        Draft202012Validator(_load_progress_schema()).validate(progress)


# ---------------------------------------------------------------------------
# Integration: Progress, logs, and whole-plan report
# ---------------------------------------------------------------------------

class TestProgressAndReportArtifacts:
    """Acceptance: Progress, logs, and a whole-plan report are produced."""

    def test_progress_json_written(
        self, tmp_path: Path, fake_agent: FakeAgentAdapter
    ) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="Step",
                verification_commands=_passing_verification(),
            ),
        )
        fake_agent.enqueue_done("STEP-001")
        automation_dir = tmp_path / ".automation"
        ctx = _prepare_context(plan_file, automation_dir)

        with patch("tools.run_plan._is_worktree_clean", return_value=True):
            run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        progress_path = automation_dir / "progress.json"
        assert progress_path.exists()
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        assert progress["schema_version"] == 1
        assert "STEP-001" in progress["steps"]

    def test_run_log_written(
        self, tmp_path: Path, fake_agent: FakeAgentAdapter
    ) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="Step",
                verification_commands=_passing_verification(),
            ),
        )
        fake_agent.enqueue_done("STEP-001")
        automation_dir = tmp_path / ".automation"
        ctx = _prepare_context(plan_file, automation_dir)

        with patch("tools.run_plan._is_worktree_clean", return_value=True):
            run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        log_path = automation_dir / "run-log.md"
        assert log_path.exists()

    def test_whole_plan_report_written_in_whole_plan_mode(
        self, tmp_path: Path, fake_agent: FakeAgentAdapter
    ) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="Step",
                verification_commands=_passing_verification(),
            ),
        )
        fake_agent.enqueue_done("STEP-001")
        automation_dir = tmp_path / ".automation"
        ctx = _prepare_context(plan_file, automation_dir)

        with patch("tools.run_plan._is_worktree_clean", return_value=True):
            run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        report_path = automation_dir / "whole-plan-report.md"
        assert report_path.exists()
        content = report_path.read_text(encoding="utf-8")
        assert "STEP-001" in content


# ---------------------------------------------------------------------------
# Integration: Max steps limit
# ---------------------------------------------------------------------------

class TestOneStepLimit:
    """Acceptance: one-step mode enforces the step limit."""

    def test_one_step_stops_after_first_step(
        self, tmp_path: Path, fake_agent: FakeAgentAdapter
    ) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="First",
                verification_commands=_passing_verification(),
            ),
            make_implementation_step(
                step_id="STEP-002",
                title="Second",
                verification_commands=_passing_verification(),
            ),
            make_implementation_step(
                step_id="STEP-003",
                title="Third",
                verification_commands=_passing_verification(),
            ),
        )
        fake_agent.enqueue_done("STEP-001")
        automation_dir = tmp_path / ".automation"
        ctx = _prepare_context(plan_file, automation_dir)

        with (
            patch("tools.run_plan._is_worktree_clean", return_value=True),
        ):
            exit_code = run(
                ctx,
                one_step=True,
                adapter=fake_agent,
                change_detector=FakeChangeDetector({}),
            )

        assert exit_code == 0
        assert len(fake_agent.invocations) == 1

        progress = _load_progress(automation_dir)
        assert progress["steps"]["STEP-001"]["state"] == "DONE"
        assert progress["steps"]["STEP-002"]["state"] == "TODO"


# ---------------------------------------------------------------------------
# Integration: Prepare-only setup
# ---------------------------------------------------------------------------

class TestPrepareRunOnly:
    """prepare_run initializes state without invoking an agent."""

    def test_prepare_run_does_not_invoke_agent(
        self, tmp_path: Path, fake_agent: FakeAgentAdapter
    ) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="Step",
                verification_commands=_passing_verification(),
            ),
        )
        automation_dir = tmp_path / ".automation"
        ctx = _prepare_context(plan_file, automation_dir)

        assert ctx["error"] is None
        assert len(fake_agent.invocations) == 0
        assert (automation_dir / "progress.json").exists()


# ---------------------------------------------------------------------------
# Integration: Resume from progress
# ---------------------------------------------------------------------------

class TestResumeFromProgress:
    """Resume picks up from the previous progress state."""

    def test_resume_skips_done_steps(
        self, tmp_path: Path, fake_agent: FakeAgentAdapter
    ) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="Already done",
                verification_commands=_passing_verification(),
            ),
            make_implementation_step(
                step_id="STEP-002",
                title="Needs work",
                verification_commands=_passing_verification(),
            ),
        )
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir(parents=True, exist_ok=True)

        # Pre-seed progress with STEP-001 already DONE.
        progress = {
            "schema_version": 1,
            "plan_file": str(plan_file),
            "last_run_id": "RUN-2025-01-01T00:00:00Z",
            "steps": {
                "STEP-001": {
                    "state": "DONE",
                    "agent": "spec-implementer",
                    "model": "default",
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
                                    str(
                                        automation_dir
                                        / "verification"
                                        / "STEP-001"
                                        / "attempt-1-command-0.summary.json"
                                    ),
                                ],
                            }
                        ],
                    },
                    "fix_attempts": 0,
                    "commit": None,
                    "failure_reason": None,
                },
                "STEP-002": {
                    "state": "TODO",
                    "agent": None,
                    "model": None,
                    "started_at": None,
                    "completed_at": None,
                    "pre_analysis": None,
                    "verification": None,
                    "fix_attempts": 0,
                    "commit": None,
                    "failure_reason": None,
                },
            },
        }
        (automation_dir / "progress.json").write_text(
            json.dumps(progress, indent=2), encoding="utf-8"
        )

        fake_agent.enqueue_done("STEP-002")
        ctx = _prepare_context(plan_file, automation_dir, resume=True)

        with (
            patch("tools.run_plan._is_worktree_clean", return_value=True),
        ):
            exit_code = run(
                ctx,
                adapter=fake_agent,
                change_detector=FakeChangeDetector({}),
            )

        assert exit_code == 0
        assert len(fake_agent.invocations) == 1
        assert fake_agent.invocations[0].step_id == "STEP-002"

        updated = _load_progress(automation_dir)
        assert updated["steps"]["STEP-001"]["state"] == "DONE"
        assert updated["steps"]["STEP-002"]["state"] == "DONE"


# ---------------------------------------------------------------------------
# Integration: No adapter → error
# ---------------------------------------------------------------------------

class TestNoAdapterError:
    """Phase 1 requires an explicit adapter; omitting it is an error."""

    def test_no_adapter_returns_error(self, tmp_path: Path) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="Step",
                verification_commands=_passing_verification(),
            ),
        )
        automation_dir = tmp_path / ".automation"
        _write_system_prompts(automation_dir)
        ctx = _prepare_context(plan_file, automation_dir)

        with (
            patch("tools.run_plan._is_worktree_clean", return_value=True),
            patch("tools.orchestrator.copilot_cli_adapter.subprocess.run", side_effect=FileNotFoundError("copilot not found")),
        ):
            exit_code = run(
                ctx,
                adapter=None,
                change_detector=FakeChangeDetector({}),
            )

        assert exit_code == 2


# ---------------------------------------------------------------------------
# Integration: Full multi-step orchestration with mixed outcomes
# ---------------------------------------------------------------------------

class TestFullMultiStepOrchestration:
    """Integration of multiple modules: parse → validate → select →
    invoke → verify → progress → report, across multiple steps."""

    def test_three_steps_all_pass(
        self, tmp_path: Path, fake_agent: FakeAgentAdapter
    ) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="First",
                verification_commands=_passing_verification(),
            ),
            make_implementation_step(
                step_id="STEP-002",
                title="Second",
                verification_commands=_passing_verification(),
            ),
            make_implementation_step(
                step_id="STEP-003",
                title="Third",
                verification_commands=_passing_verification(),
            ),
        )
        fake_agent.enqueue_done("STEP-001")
        fake_agent.enqueue_done("STEP-002")
        fake_agent.enqueue_done("STEP-003")
        automation_dir = tmp_path / ".automation"
        ctx = _prepare_context(plan_file, automation_dir)

        with (
            patch("tools.run_plan._is_worktree_clean", return_value=True),
        ):
            exit_code = run(
                ctx,
                adapter=fake_agent,
                change_detector=FakeChangeDetector({}),
            )

        assert exit_code == 0
        assert len(fake_agent.invocations) == 3

        progress = _load_progress(automation_dir)
        for sid in ["STEP-001", "STEP-002", "STEP-003"]:
            assert progress["steps"][sid]["state"] == "DONE"
            assert progress["steps"][sid]["completed_at"] is not None
            assert progress["steps"][sid]["verification"]["status"] == "PASS"

        # Whole-plan report should be generated.
        report_path = automation_dir / "whole-plan-report.md"
        assert report_path.exists()
        report = report_path.read_text(encoding="utf-8")
        assert "Completed: 3" in report

    def test_step_passes_then_gate_in_whole_plan_mode(
        self, tmp_path: Path, fake_agent: FakeAgentAdapter
    ) -> None:
        plan_file = _write_plan(
            tmp_path,
            make_implementation_step(
                step_id="STEP-001",
                title="Impl",
                verification_commands=_passing_verification(),
            ),
            make_human_gate_step(step_id="STEP-002", title="Gate"),
        )
        fake_agent.enqueue_done("STEP-001")
        automation_dir = tmp_path / ".automation"
        ctx = _prepare_context(plan_file, automation_dir)

        with (
            patch("tools.run_plan._is_worktree_clean", return_value=True),
        ):
            exit_code = run(
                ctx,
                adapter=fake_agent,
                change_detector=FakeChangeDetector({}),
            )

        assert exit_code == 0

        # Report in whole-plan mode.
        report_path = automation_dir / "whole-plan-report.md"
        assert report_path.exists()
        report = report_path.read_text(encoding="utf-8")
        assert "HUMAN_GATE" in report
