"""Tests for pre-analysis runner — covers PRE-001 through PRE-006.

TDD: These tests are written before the implementation exists.
They define the expected behavior of the pre-analysis runner module.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

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


def _make_pre_analysis_command(
    cmd_id: str = "check-1",
    run: str = "echo ok",
    purpose: str = "Diagnostic check",
    fail_on_nonzero: bool = True,
    include_output_in_prompt: bool = False,
    max_output_chars: int = 4096,
) -> dict[str, Any]:
    """Build a single pre-analysis command dict."""
    return {
        "id": cmd_id,
        "run": run,
        "purpose": purpose,
        "fail_on_nonzero": fail_on_nonzero,
        "include_output_in_prompt": include_output_in_prompt,
        "max_output_chars": max_output_chars,
    }


def _make_file_output_pre_analysis_command(
    cmd_id: str = "file-output",
    run: str = "echo ok",
    purpose: str = "Generate file evidence",
    fail_on_nonzero: bool = True,
    output_files: list[str] | None = None,
) -> dict[str, Any]:
    """Build a file-based pre-analysis command dict."""
    if output_files is None:
        output_files = []
    return {
        "id": cmd_id,
        "run": run,
        "purpose": purpose,
        "fail_on_nonzero": fail_on_nonzero,
        "output_files": output_files,
    }


def _step_with_pre_analysis(
    commands: list[dict[str, Any]],
    step_id: str = "STEP-001",
    title: str = "Step with pre-analysis",
) -> str:
    """Build a plan step that includes a pre_analysis block."""
    return make_implementation_step(
        step_id=step_id,
        title=title,
        pre_analysis={"commands": commands},
    )


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git in a temporary repository for pre-analysis tests."""
    if shutil.which("git") is None:
        pytest.skip("git is required for Git-visible mutation tests")
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _make_git_repo(tmp_path: Path) -> Path:
    """Create a clean temporary Git repository with ignored automation paths."""
    repo = tmp_path / "repo"
    repo.mkdir()

    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "wfrunner@example.test")
    _run_git(repo, "config", "user.name", "WaterfallRunner Tests")

    (repo / ".gitignore").write_text(
        ".automation/\nignored-output/\n*.ignored\n",
        encoding="utf-8",
    )
    (repo / "tracked.txt").write_text("original\n", encoding="utf-8")
    _run_git(repo, "add", ".gitignore", "tracked.txt")
    _run_git(repo, "commit", "-m", "initial")

    return repo


def _python_write_command(path: Path, text: str) -> str:
    """Build a shell command that writes text through Python."""
    return (
        "python -c \"from pathlib import Path; "
        f"Path({str(path)!r}).write_text({text!r}, encoding='utf-8')\""
    )


# ===========================================================================
# PRE-001: No pre_analysis property → proceed to agent invocation
# ===========================================================================


class TestPRE001NoPeAnalysisProperty:
    """When a step has no pre_analysis, the orchestrator should proceed directly
    to agent invocation without running any pre-analysis commands."""

    def test_step_without_pre_analysis_has_no_pre_analysis_key(self) -> None:
        """A step without pre_analysis should parse with no pre_analysis field."""
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="No pre-analysis"),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        # The yaml_block should not contain a pre_analysis key.
        assert "pre_analysis" not in step.yaml_block

    def test_no_pre_analysis_means_no_commands_to_run(self) -> None:
        """When pre_analysis is absent, the runner should return an empty result
        or skip entirely, allowing agent invocation to proceed."""
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="No pre-analysis"),
        )
        steps = _parse_steps(plan)
        step = steps[0]

        result = run_pre_analysis(step, automation_dir=Path("/tmp/fake-automation"))

        assert result.ok is True
        assert len(result.command_results) == 0


# ===========================================================================
# PRE-002: Pre-analysis command exits zero → save output and proceed
# ===========================================================================


class TestPRE002CommandExitsZero:
    """When a pre-analysis command exits 0, the orchestrator should save
    the full output and proceed to agent invocation."""

    def test_zero_exit_saves_output_and_proceeds(self, tmp_path: Path) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="check-ok",
                    run="echo hello",
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_pre_analysis(step, automation_dir=automation_dir)

        assert result.ok is True
        assert len(result.command_results) == 1
        cmd_result = result.command_results[0]
        assert cmd_result.exit_code == 0
        assert cmd_result.status == "PASS"

    def test_zero_exit_stores_full_log(self, tmp_path: Path) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="check-log",
                    run="echo log-output",
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        _result = run_pre_analysis(step, automation_dir=automation_dir)

        # Full log should be written to the expected path.
        log_dir = automation_dir / "pre-analysis" / "STEP-001"
        assert log_dir.exists()
        log_files = list(log_dir.glob("check-log.log"))
        assert len(log_files) == 1

    def test_zero_exit_stores_summary_json(self, tmp_path: Path) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="check-summary",
                    run="echo summary-test",
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        _result = run_pre_analysis(step, automation_dir=automation_dir)

        summary_dir = automation_dir / "pre-analysis" / "STEP-001"
        summary_files = list(summary_dir.glob("check-summary.summary.json"))
        assert len(summary_files) == 1


# ===========================================================================
# PRE-003: Pre-analysis command exits nonzero with fail_on_nonzero: true
#          → stop before agent invocation
# ===========================================================================


class TestPRE003NonzeroExitWithFailOnNonzero:
    """When a command exits nonzero and fail_on_nonzero is true,
    the orchestrator should stop before agent invocation."""

    def test_nonzero_exit_with_fail_on_nonzero_stops(self, tmp_path: Path) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="fail-check",
                    run="exit 1",
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_pre_analysis(step, automation_dir=automation_dir)

        assert result.ok is False
        assert len(result.command_results) == 1
        cmd_result = result.command_results[0]
        assert cmd_result.exit_code != 0
        assert cmd_result.status == "FAIL"

    def test_nonzero_exit_records_failure_reason(self, tmp_path: Path) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="fail-reason",
                    run="exit 2",
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_pre_analysis(step, automation_dir=automation_dir)

        assert result.ok is False
        assert result.failure_reason is not None
        assert "fail-reason" in result.failure_reason


# ===========================================================================
# PRE-004: Pre-analysis command exits nonzero with fail_on_nonzero: false
#          → save output and proceed
# ===========================================================================


class TestPRE004NonzeroExitWithoutFailOnNonzero:
    """When a command exits nonzero but fail_on_nonzero is false,
    the orchestrator should save output and proceed."""

    def test_nonzero_exit_with_fail_on_nonzero_false_proceeds(
        self, tmp_path: Path
    ) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="warn-check",
                    run="exit 1",
                    fail_on_nonzero=False,
                )],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_pre_analysis(step, automation_dir=automation_dir)

        assert result.ok is True
        assert len(result.command_results) == 1
        cmd_result = result.command_results[0]
        assert cmd_result.exit_code != 0
        # Status should indicate a warning but not a blocking failure.
        assert cmd_result.status in ("PASS", "WARN")

    def test_nonzero_exit_output_still_saved(self, tmp_path: Path) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="warn-log",
                    run="exit 1",
                    fail_on_nonzero=False,
                )],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        _result = run_pre_analysis(step, automation_dir=automation_dir)

        log_dir = automation_dir / "pre-analysis" / "STEP-001"
        assert log_dir.exists()


# ===========================================================================
# PRE-005: Pre-analysis changes working tree → stop before agent invocation
# ===========================================================================


class TestPRE005ChangesWorkingTree:
    """If pre-analysis modifies the working tree, the orchestrator must stop."""

    def test_working_tree_modified_stops(self, tmp_path: Path) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        # Create a file that the command will modify.
        target_file = tmp_path / "canary.txt"
        target_file.write_text("original", encoding="utf-8")

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="mutating-check",
                    run=f"echo modified > {target_file}",
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_pre_analysis(
            step, automation_dir=automation_dir, working_dir=tmp_path
        )

        assert result.ok is False
        assert result.tree_modified is True

    def test_working_tree_unmodified_proceeds(self, tmp_path: Path) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="readonly-check",
                    run="echo readonly",
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_pre_analysis(
            step, automation_dir=automation_dir, working_dir=tmp_path
        )

        assert result.ok is True
        assert result.tree_modified is False


class TestPRE005GitVisibleMutationTracking:
    """Pre-analysis mutation detection should follow Git-visible semantics."""

    def test_git_visible_repository_change_sets_tree_modified_and_stops(
        self, tmp_path: Path
    ) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        repo = _make_git_repo(tmp_path)
        automation_dir = repo / ".automation"
        automation_dir.mkdir()
        tracked_file = repo / "tracked.txt"

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="git-visible-mutation",
                    run=_python_write_command(tracked_file, "modified\n"),
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]

        result = run_pre_analysis(
            step, automation_dir=automation_dir, working_dir=repo
        )

        assert result.ok is False
        assert result.tree_modified is True
        assert result.command_results[0].status == "PASS"

    def test_ignored_path_change_is_not_tree_modified(
        self, tmp_path: Path
    ) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        repo = _make_git_repo(tmp_path)
        automation_dir = repo / ".automation"
        automation_dir.mkdir()
        ignored_dir = repo / "ignored-output"
        ignored_dir.mkdir()
        ignored_file = ignored_dir / "pre-analysis.txt"

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="ignored-mutation",
                    run=_python_write_command(ignored_file, "ignored\n"),
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]

        result = run_pre_analysis(
            step, automation_dir=automation_dir, working_dir=repo
        )

        assert result.ok is True
        assert result.tree_modified is False
        assert ignored_file.read_text(encoding="utf-8") == "ignored\n"

    def test_automation_logs_do_not_count_as_repository_mutations(
        self, tmp_path: Path
    ) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        repo = _make_git_repo(tmp_path)
        automation_dir = repo / ".automation"
        automation_dir.mkdir()

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="automation-log",
                    run="echo log-only",
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]

        result = run_pre_analysis(
            step, automation_dir=automation_dir, working_dir=repo
        )

        log_dir = automation_dir / "pre-analysis" / "STEP-001"
        assert result.ok is True
        assert result.tree_modified is False
        assert (log_dir / "automation-log.log").exists()
        assert (log_dir / "automation-log.summary.json").exists()

    def test_log_writing_remains_intact_in_git_repo(
        self, tmp_path: Path
    ) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        repo = _make_git_repo(tmp_path)
        automation_dir = repo / ".automation"
        automation_dir.mkdir()

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="log-output",
                    run="echo log-ready-output",
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]

        result = run_pre_analysis(
            step, automation_dir=automation_dir, working_dir=repo
        )

        cmd_result = result.command_results[0]
        log_dir = automation_dir / "pre-analysis" / "STEP-001"
        assert result.ok is True
        assert result.tree_modified is False
        assert not hasattr(cmd_result, "prompt_excerpt")
        assert "log-ready-output" in (log_dir / "log-output.log").read_text(
            encoding="utf-8"
        )
        assert (log_dir / "log-output.summary.json").exists()


# ===========================================================================
# PRE-006: Pre-analysis output exceeds max prompt size
#          → store full log and pass bounded excerpt only
# ===========================================================================


class TestPRE006OutputExceedsMaxPromptSize:
    """Large pre-analysis output is kept in logs, not prompt excerpts."""

    def test_large_output_does_not_create_prompt_excerpt(self, tmp_path: Path) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="big-output",
                    run="python -c \"print('x' * 10000)\"",
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_pre_analysis(step, automation_dir=automation_dir)

        assert result.ok is True
        assert len(result.command_results) == 1
        cmd_result = result.command_results[0]
        assert not hasattr(cmd_result, "prompt_excerpt")

    def test_large_output_full_log_is_stored(self, tmp_path: Path) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="big-log",
                    run="python -c \"print('x' * 10000)\"",
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        _result = run_pre_analysis(step, automation_dir=automation_dir)

        # Full log should contain the entire output, not truncated.
        log_dir = automation_dir / "pre-analysis" / "STEP-001"
        log_file = log_dir / "big-log.log"
        assert log_file.exists()
        full_content = log_file.read_text(encoding="utf-8")
        assert len(full_content) > 100

    def test_no_prompt_excerpt_field_is_exposed(self, tmp_path: Path) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="log-only",
                    run="echo log-only",
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_pre_analysis(step, automation_dir=automation_dir)

        assert result.ok is True
        cmd_result = result.command_results[0]
        assert not hasattr(cmd_result, "prompt_excerpt")


class TestPreAnalysisFileBasedEvidence:
    """Pre-analysis evidence is represented as files, not prompt excerpts."""

    def test_declared_output_files_are_recorded_in_summary(self, tmp_path: Path) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        automation_dir = tmp_path / ".automation"
        artifact_path = automation_dir / "analysis" / "coverage.txt"
        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_file_output_pre_analysis_command(
                    cmd_id="coverage-file",
                    run=_python_write_command(artifact_path, "coverage evidence\n"),
                    output_files=[str(artifact_path)],
                )],
            ),
        )
        steps = _parse_steps(plan)
        automation_dir.mkdir()

        result = run_pre_analysis(steps[0], automation_dir=automation_dir)

        summary_path = automation_dir / "pre-analysis" / "STEP-001" / "coverage-file.summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert result.command_results[0].output_files == [str(artifact_path)]
        assert summary["output_files"] == [str(artifact_path)]
        assert artifact_path.read_text(encoding="utf-8") == "coverage evidence\n"

    def test_command_result_does_not_expose_prompt_excerpt(self, tmp_path: Path) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_file_output_pre_analysis_command(
                    cmd_id="no-excerpt",
                    run="echo file-based",
                )],
            ),
        )
        steps = _parse_steps(plan)
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_pre_analysis(steps[0], automation_dir=automation_dir)

        assert not hasattr(result.command_results[0], "prompt_excerpt")

    def test_legacy_prompt_fields_no_longer_create_prompt_excerpt(self, tmp_path: Path) -> None:
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="legacy-prompt-field",
                    run="echo should-stay-in-log",
                    include_output_in_prompt=True,
                    max_output_chars=5,
                )],
            ),
        )
        steps = _parse_steps(plan)
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_pre_analysis(steps[0], automation_dir=automation_dir)

        assert not hasattr(result.command_results[0], "prompt_excerpt")


# ---------------------------------------------------------------------------
# ScriptOutcome three-state tests — STEP-003
# ---------------------------------------------------------------------------

class TestScriptOutcomePreAnalysisPass:
    """ScriptOutcome.PASS when command exits 0."""

    def test_exit_zero_yields_pass_outcome(self, tmp_path: Path) -> None:
        from tools.constants import ScriptOutcome
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="pass-check",
                    run="echo ok",
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_pre_analysis(steps[0], automation_dir=automation_dir)

        assert result.ok is True
        cmd_result = result.command_results[0]
        assert cmd_result.outcome == ScriptOutcome.PASS


class TestScriptOutcomePreAnalysisFail:
    """ScriptOutcome.FAIL when command exits nonzero (well-formed failure)."""

    def test_nonzero_exit_yields_fail_outcome(self, tmp_path: Path) -> None:
        from tools.constants import ScriptOutcome
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="fail-check",
                    run="python -c \"import sys; sys.exit(1)\"",
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        result = run_pre_analysis(steps[0], automation_dir=automation_dir)

        assert result.ok is False
        cmd_result = result.command_results[0]
        assert cmd_result.outcome == ScriptOutcome.FAIL


class TestScriptOutcomePreAnalysisError:
    """ScriptOutcome.ERROR when script cannot execute (crash, timeout, missing)."""

    def test_file_not_found_yields_error_outcome(self, tmp_path: Path) -> None:
        from tools.constants import ScriptOutcome
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="error-check",
                    run="nonexistent_command_that_does_not_exist_xyz_99",
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        # Mock subprocess.run to raise FileNotFoundError (shell=True masks it on Windows)
        with patch("tools.orchestrator.pre_analysis_runner.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("No such file")
            result = run_pre_analysis(steps[0], automation_dir=automation_dir)

        # The command should have an ERROR outcome
        cmd_result = result.command_results[0]
        assert cmd_result.outcome == ScriptOutcome.ERROR

    def test_timeout_yields_error_outcome(self, tmp_path: Path) -> None:
        from tools.constants import ScriptOutcome
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="timeout-check",
                    run="python -c \"import time; time.sleep(999)\"",
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        # Mock subprocess.run to raise TimeoutExpired
        with patch("tools.orchestrator.pre_analysis_runner.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=300)
            result = run_pre_analysis(steps[0], automation_dir=automation_dir)

        cmd_result = result.command_results[0]
        assert cmd_result.outcome == ScriptOutcome.ERROR


# ===========================================================================
# STEP-031 RED: Pre-analysis uses configurable timeout
# ===========================================================================


class TestPreAnalysisConfigurableTimeout:
    """Verify pre-analysis runner accepts and uses a configurable timeout."""

    def test_run_pre_analysis_accepts_timeout_parameter(self, tmp_path: Path) -> None:
        """run_pre_analysis should accept a timeout_seconds keyword argument."""
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="timeout-param",
                    run="echo ok",
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        # Should accept timeout_seconds without error
        result = run_pre_analysis(
            steps[0],
            automation_dir=automation_dir,
            timeout_seconds=600,
        )
        assert result.ok is True

    def test_configured_timeout_is_passed_to_subprocess(self, tmp_path: Path) -> None:
        """run_pre_analysis should pass timeout_seconds to subprocess.run."""
        from tools.orchestrator.pre_analysis_runner import run_pre_analysis

        plan = make_plan(
            _step_with_pre_analysis(
                commands=[_make_pre_analysis_command(
                    cmd_id="timeout-forwarded",
                    run="echo hello",
                    fail_on_nonzero=True,
                )],
            ),
        )
        steps = _parse_steps(plan)
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        with patch("tools.orchestrator.pre_analysis_runner.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["echo", "hello"], returncode=0, stdout="hello\n", stderr="",
            )
            run_pre_analysis(
                steps[0],
                automation_dir=automation_dir,
                timeout_seconds=900,
            )

        # Verify subprocess.run was called with timeout=900
        assert mock_run.call_count >= 1
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("timeout") == 900 or call_kwargs[1].get("timeout") == 900
