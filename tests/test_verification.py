"""Tests for verification runner — covers VER-001 through VER-006.

TDD: These tests are written before the implementation exists.
They define the expected behavior of the verification runner module.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from tests.helpers import (
    make_implementation_step,
    make_plan,
)
from tools.plan_parser import parse_plan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_steps(plan_text: str):
    """Parse a plan and return the list of parsed steps."""
    result = parse_plan(plan_text)
    assert result.ok, f"Plan parse errors: {result.errors}"
    return result.steps


def _step_with_verification(
    commands: list[str],
    step_id: str = "STEP-001",
    title: str = "Step with verification",
) -> str:
    """Build a plan step with the given verification commands."""
    return make_implementation_step(
        step_id=step_id,
        title=title,
        verification_commands=['"' + c.replace('"', '\\"') + '"' for c in commands],
    )


def _step_with_empty_verification(
    step_id: str = "STEP-001",
    title: str = "Step without verification commands",
) -> str:
    """Build a plan step with an empty verification commands list."""
    return textwrap.dedent(f"""\
        ### {step_id} — {title}

        ```yaml
        schema_version: 1
        id: {step_id}
        title: {title}
        type: IMPLEMENTATION
        agent: spec-implementer
        prompt: prompts/implement-step.md
        model: default
        allowed_files:
          - tools/__init__.py
        verification:
          commands: []
        retry:
          max_fix_attempts: 0
        ```
    """)


# ===========================================================================
# VER-001: Single verification command exits zero → step can complete
# ===========================================================================


class TestVER001SingleCommandExitsZero:
    """When a single verification command exits 0, the step should
    be considered as having passed verification."""

    def test_single_command_passes(self, tmp_path: Path) -> None:
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_verification(commands=["python -c \"print('ok')\""]),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_verification(step, automation_dir=automation_dir, attempt=1)

        assert result.ok is True
        assert len(result.command_results) == 1
        assert result.command_results[0].exit_code == 0
        assert result.command_results[0].status == "PASS"

    def test_single_command_stores_log(self, tmp_path: Path) -> None:
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_verification(commands=["python -c \"print('hello')\""])
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        _result = run_verification(step, automation_dir=automation_dir, attempt=1)

        log_dir = automation_dir / "verification" / "STEP-001"
        assert log_dir.exists()
        log_files = list(log_dir.glob("attempt-1-command-0.log"))
        assert len(log_files) == 1

    def test_single_command_stores_summary(self, tmp_path: Path) -> None:
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_verification(commands=["python -c \"print('summary')\""])
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        _result = run_verification(step, automation_dir=automation_dir, attempt=1)

        summary_dir = automation_dir / "verification" / "STEP-001"
        summary_files = list(summary_dir.glob("attempt-1-command-0.summary.json"))
        assert len(summary_files) == 1

    def test_single_command_summary_has_required_fields(self, tmp_path: Path) -> None:
        import json
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_verification(commands=["python -c \"print('fields')\""])
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        _result = run_verification(step, automation_dir=automation_dir, attempt=1)

        summary_path = automation_dir / "verification" / "STEP-001" / "attempt-1-command-0.summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))

        assert summary["step_id"] == "STEP-001"
        assert summary["attempt"] == 1
        assert summary["command_index"] == 0
        assert summary["exit_code"] == 0
        assert summary["status"] == "PASS"
        assert "duration_seconds" in summary
        assert "stdout_tail" in summary
        assert "stderr_tail" in summary
        assert "log_path" in summary


# ===========================================================================
# VER-002: First verification command fails → stop or retry
# ===========================================================================


class TestVER002FirstCommandFails:
    """When the first (or only) verification command fails,
    verification should be marked as failed."""

    def test_first_command_fails_marks_verification_failed(self, tmp_path: Path) -> None:
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_verification(commands=["python -c \"raise SystemExit(1)\""]),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_verification(step, automation_dir=automation_dir, attempt=1)

        assert result.ok is False
        assert len(result.command_results) == 1
        assert result.command_results[0].exit_code != 0
        assert result.command_results[0].status == "FAIL"

    def test_first_command_fails_stores_log(self, tmp_path: Path) -> None:
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_verification(commands=["python -c \"raise SystemExit(1)\""]),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        run_verification(step, automation_dir=automation_dir, attempt=1)

        log_dir = automation_dir / "verification" / "STEP-001"
        log_files = list(log_dir.glob("attempt-1-command-0.log"))
        assert len(log_files) == 1

    def test_first_command_fails_records_exit_code(self, tmp_path: Path) -> None:
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_verification(commands=["python -c \"raise SystemExit(42)\""]),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_verification(step, automation_dir=automation_dir, attempt=1)

        assert result.command_results[0].exit_code == 42


# ===========================================================================
# VER-003: Multiple commands, later command fails → treat as failed
# ===========================================================================


class TestVER003LaterCommandFails:
    """When multiple verification commands are listed and a later
    command fails, the entire verification should be treated as failed."""

    def test_second_command_fails_marks_verification_failed(self, tmp_path: Path) -> None:
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_verification(commands=[
                "python -c \"print('pass')\"",
                "python -c \"raise SystemExit(1)\"",
            ]),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_verification(step, automation_dir=automation_dir, attempt=1)

        assert result.ok is False

    def test_first_command_passes_second_fails(self, tmp_path: Path) -> None:
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_verification(commands=[
                "python -c \"print('ok')\"",
                "python -c \"raise SystemExit(1)\"",
            ]),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_verification(step, automation_dir=automation_dir, attempt=1)

        # First command should pass.
        assert result.command_results[0].status == "PASS"
        assert result.command_results[0].exit_code == 0
        # Second command should fail.
        assert result.command_results[1].status == "FAIL"
        assert result.command_results[1].exit_code != 0

    def test_stops_at_first_failure_does_not_run_remaining(self, tmp_path: Path) -> None:
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_verification(commands=[
                "python -c \"print('ok')\"",
                "python -c \"raise SystemExit(1)\"",
                "python -c \"print('should not run')\"",
            ]),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_verification(step, automation_dir=automation_dir, attempt=1)

        assert result.ok is False
        # Should only have results for commands up to and including the failure.
        assert len(result.command_results) == 2

    def test_all_commands_pass_means_verification_passes(self, tmp_path: Path) -> None:
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_verification(commands=[
                "python -c \"print('a')\"",
                "python -c \"print('b')\"",
                "python -c \"print('c')\"",
            ]),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_verification(step, automation_dir=automation_dir, attempt=1)

        assert result.ok is True
        assert len(result.command_results) == 3
        for cr in result.command_results:
            assert cr.status == "PASS"


# ===========================================================================
# VER-004: Verification command times out → treat as failed
# ===========================================================================


class TestVER004CommandTimesOut:
    """When a verification command exceeds its timeout, the orchestrator
    should treat verification as failed with a TIMEOUT status."""

    def test_timeout_marks_verification_failed(self, tmp_path: Path) -> None:
        from tools.orchestrator.verification import run_verification

        # Use a command that would hang, with a very short timeout.
        plan = make_plan(
            _step_with_verification(commands=["python -c \"import time; time.sleep(60)\""]),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_verification(
            step, automation_dir=automation_dir, attempt=1, timeout_seconds=1,
        )

        assert result.ok is False
        assert len(result.command_results) == 1
        assert result.command_results[0].status == "TIMEOUT"

    def test_timeout_records_duration(self, tmp_path: Path) -> None:
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_verification(commands=["python -c \"import time; time.sleep(60)\""]),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_verification(
            step, automation_dir=automation_dir, attempt=1, timeout_seconds=1,
        )

        # Duration should be approximately the timeout value.
        assert result.command_results[0].duration_seconds >= 0.5


# ===========================================================================
# VER-005: Verification output is large → store full log, report excerpt
# ===========================================================================


class TestVER005LargeOutput:
    """When verification produces large output, the full log should be
    stored and only a bounded excerpt should be included in the summary."""

    def test_large_output_stored_in_full_log(self, tmp_path: Path) -> None:
        from tools.orchestrator.verification import run_verification

        # Generate a large output.
        plan = make_plan(
            _step_with_verification(commands=[
                "python -c \"print('x' * 50000)\"",
            ]),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_verification(step, automation_dir=automation_dir, attempt=1)

        assert result.ok is True
        log_path = automation_dir / "verification" / "STEP-001" / "attempt-1-command-0.log"
        log_content = log_path.read_text(encoding="utf-8")
        # Full output should be stored.
        assert len(log_content) >= 50000

    def test_large_output_excerpt_is_bounded(self, tmp_path: Path) -> None:
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_verification(commands=[
                "python -c \"print('x' * 50000)\"",
            ]),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_verification(step, automation_dir=automation_dir, attempt=1)

        # stdout_tail should be bounded (not the full 50000 chars).
        cmd_result = result.command_results[0]
        assert len(cmd_result.stdout_tail) < 50000
        assert len(cmd_result.stdout_tail) > 0

    def test_large_stderr_excerpt_is_bounded(self, tmp_path: Path) -> None:
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_verification(commands=[
                "python -c \"import sys; sys.stderr.write('e' * 50000)\"",
            ]),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_verification(step, automation_dir=automation_dir, attempt=1)

        cmd_result = result.command_results[0]
        assert len(cmd_result.stderr_tail) < 50000
        assert len(cmd_result.stderr_tail) > 0


# ===========================================================================
# VER-006: verification.commands is empty → step can complete without
#          verification command execution
# ===========================================================================


class TestVER006EmptyVerificationCommands:
    """When verification.commands is empty, the step should complete
    after scope checks without any verification command execution."""

    def test_empty_commands_passes_verification(self, tmp_path: Path) -> None:
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_empty_verification(),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_verification(step, automation_dir=automation_dir, attempt=1)

        assert result.ok is True
        assert len(result.command_results) == 0

    def test_empty_commands_creates_no_log_files(self, tmp_path: Path) -> None:
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_empty_verification(),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()
        assert step.yaml_block["verification"]["commands"] == []

        run_verification(step, automation_dir=automation_dir, attempt=1)

        ver_dir = automation_dir / "verification" / "STEP-001"
        # Either the directory doesn't exist, or it's empty.
        if ver_dir.exists():
            assert len(list(ver_dir.iterdir())) == 0

    def test_empty_commands_no_verification_executed(self, tmp_path: Path) -> None:
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_empty_verification(),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_verification(step, automation_dir=automation_dir, attempt=1)

        # No commands should have been executed.
        assert result.ok is True
        assert result.command_results == []


# ---------------------------------------------------------------------------
# ScriptOutcome three-state tests — STEP-005
# ---------------------------------------------------------------------------

class TestScriptOutcomeVerificationPass:
    """ScriptOutcome.PASS when verification command exits 0."""

    def test_exit_zero_yields_pass_outcome(self, tmp_path: Path) -> None:
        from tools.constants import ScriptOutcome
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_verification(
                commands=["python -c \"print('ok')\""],
            ),
        )
        steps = _parse_steps(plan)
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_verification(steps[0], automation_dir=automation_dir, attempt=1)

        assert result.ok is True
        cmd_result = result.command_results[0]
        assert cmd_result.outcome == ScriptOutcome.PASS


class TestScriptOutcomeVerificationFail:
    """ScriptOutcome.FAIL when verification command exits nonzero."""

    def test_nonzero_exit_yields_fail_outcome(self, tmp_path: Path) -> None:
        from tools.constants import ScriptOutcome
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_verification(
                commands=["python -c \"import sys; sys.exit(1)\""],
            ),
        )
        steps = _parse_steps(plan)
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_verification(steps[0], automation_dir=automation_dir, attempt=1)

        assert result.ok is False
        cmd_result = result.command_results[0]
        assert cmd_result.outcome == ScriptOutcome.FAIL


class TestScriptOutcomeVerificationError:
    """ScriptOutcome.ERROR when verification script cannot execute."""

    def test_file_not_found_yields_error_outcome(self, tmp_path: Path) -> None:
        from unittest.mock import patch
        from tools.constants import ScriptOutcome
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_verification(
                commands=["echo test"],
            ),
        )
        steps = _parse_steps(plan)
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        with patch("tools.orchestrator.verification.subprocess.Popen") as mock_popen:
            mock_popen.side_effect = FileNotFoundError("No such file")
            result = run_verification(steps[0], automation_dir=automation_dir, attempt=1)

        cmd_result = result.command_results[0]
        assert cmd_result.outcome == ScriptOutcome.ERROR


    def test_timeout_yields_error_outcome(self, tmp_path: Path) -> None:
        import subprocess
        from unittest.mock import patch, MagicMock
        from tools.constants import ScriptOutcome
        from tools.orchestrator.verification import run_verification

        plan = make_plan(
            _step_with_verification(
                commands=["echo test"],
            ),
        )
        steps = _parse_steps(plan)
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=300)
        mock_proc.pid = 12345
        mock_proc.wait.return_value = None

        with patch("tools.orchestrator.verification.subprocess.Popen", return_value=mock_proc):
            with patch("tools.orchestrator.verification.subprocess.run"):
                result = run_verification(steps[0], automation_dir=automation_dir, attempt=1)

        cmd_result = result.command_results[0]
        assert cmd_result.outcome == ScriptOutcome.ERROR


class TestVerificationResultOkUsesScriptOutcome:
    """VerificationResult.ok is driven by ScriptOutcome, not legacy strings."""

    @staticmethod
    def _command_result(
        *,
        status: str,
        outcome: "ScriptOutcome",
    ) -> "VerificationCommandResult":
        from tools.orchestrator.verification import VerificationCommandResult

        return VerificationCommandResult(
            command_index=0,
            command="python -m pytest tests -q",
            exit_code=0,
            status=status,
            duration_seconds=0.1,
            stdout_tail="",
            stderr_tail="",
            log_path="verification.log",
            outcome=outcome,
        )

    def test_ok_true_when_outcome_pass_even_if_legacy_status_is_fail(self) -> None:
        from tools.constants import ScriptOutcome
        from tools.orchestrator.verification import VerificationResult

        result = VerificationResult(
            command_results=[
                self._command_result(status="FAIL", outcome=ScriptOutcome.PASS),
            ],
        )

        assert result.ok is True

    def test_ok_false_when_legacy_status_pass_but_outcome_is_fail(self) -> None:
        from tools.constants import ScriptOutcome
        from tools.orchestrator.verification import VerificationResult

        result = VerificationResult(
            command_results=[
                self._command_result(status="PASS", outcome=ScriptOutcome.FAIL),
            ],
        )

        assert result.ok is False
