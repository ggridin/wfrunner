"""Pre-analysis runner — executes pre-analysis commands before agent invocation."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from tools.plan_parser import ParsedStep
from tools.constants import (
    FIELD_COMMANDS,
    FIELD_ID,
    FIELD_PRE_ANALYSIS,
    PA_FIELD_FAIL_ON_NONZERO,
    PA_FIELD_ID,
    PA_FIELD_OUTPUT_FILES,
    PA_FIELD_RUN,
    ScriptOutcome,
    VERIFY_FAIL,
    VERIFY_PASS,
    VERIFY_WARN,
)
from tools.orchestrator.git import git_visible_snapshot


@dataclass
class PreAnalysisCommandResult:
    """Result of a single pre-analysis command execution."""

    command_id: str
    command: str
    exit_code: int
    status: str  # "PASS", "FAIL", "WARN"
    duration_seconds: float
    stdout: str
    stderr: str
    output_files: list[str] = field(default_factory=list)
    outcome: ScriptOutcome = ScriptOutcome.PASS
    summary_path: str = ""


@dataclass
class PreAnalysisResult:
    """Aggregate result of all pre-analysis commands for a step."""

    command_results: list[PreAnalysisCommandResult] = field(default_factory=list)
    failure_reason: str | None = None
    tree_modified: bool = False

    @property
    def ok(self) -> bool:
        if self.tree_modified:
            return False
        if self.failure_reason is not None:
            return False
        return all(cr.status != VERIFY_FAIL for cr in self.command_results)


def _filesystem_snapshot(working_dir: Path, ignored_root: Path) -> dict[str, float]:
    """Take a non-Git fallback snapshot for isolated temporary directories."""
    snapshot: dict[str, float] = {}
    if not working_dir.exists():
        return snapshot

    ignored_root = ignored_root.resolve()
    for path in working_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            resolved_path = path.resolve()
            resolved_path.relative_to(ignored_root)
            continue
        except ValueError:
            pass
        except OSError:
            continue

        try:
            snapshot[str(resolved_path)] = path.stat().st_mtime
        except OSError:
            pass
    return snapshot


def _fallback_tree_changed(before: dict[str, float], after: dict[str, float]) -> bool:
    """Detect whether a non-Git fallback snapshot changed."""
    if set(before.keys()) != set(after.keys()):
        return True
    for path, mtime in before.items():
        if after.get(path) != mtime:
            return True
    return False


def run_pre_analysis(
    step: ParsedStep,
    *,
    automation_dir: Path,
    working_dir: Path | None = None,
    timeout_seconds: int = 300,
) -> PreAnalysisResult:
    """Run pre-analysis commands for a step.

    Args:
        step: The parsed step containing pre_analysis metadata.
        automation_dir: Path to the .automation directory.
        working_dir: Working directory for tree-change detection.
            If None, tree-change detection is skipped.

    Returns:
        A PreAnalysisResult with per-command outcomes.
    """
    result = PreAnalysisResult()

    pre_analysis = step.yaml_block.get(FIELD_PRE_ANALYSIS)
    if pre_analysis is None:
        return result

    commands = pre_analysis.get(FIELD_COMMANDS, [])
    if not commands:
        return result

    step_id = step.yaml_block[FIELD_ID]
    log_dir = automation_dir / "pre-analysis" / step_id
    log_dir.mkdir(parents=True, exist_ok=True)

    # Take tree snapshot before running commands.
    before_git_snapshot: str | None = None
    before_fallback_snapshot: dict[str, float] = {}
    if working_dir is not None:
        before_git_snapshot = git_visible_snapshot(working_dir)
        if before_git_snapshot is None:
            before_fallback_snapshot = _filesystem_snapshot(working_dir, automation_dir)

    for cmd_spec in commands:
        cmd_id = cmd_spec[PA_FIELD_ID]
        run_cmd = cmd_spec[PA_FIELD_RUN]
        fail_on_nonzero = cmd_spec.get(PA_FIELD_FAIL_ON_NONZERO, True)
        output_files = list(cmd_spec.get(PA_FIELD_OUTPUT_FILES) or [])
        for output_file in output_files:
            output_parent = Path(output_file).parent
            if str(output_parent) != ".":
                output_parent.mkdir(parents=True, exist_ok=True)

        start = time.monotonic()
        outcome = ScriptOutcome.PASS
        try:
            proc = subprocess.run(
                run_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            exit_code = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
            if exit_code == 0:
                outcome = ScriptOutcome.PASS
            else:
                outcome = ScriptOutcome.FAIL
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            exit_code = -1
            stdout = ""
            stderr = str(exc)
            outcome = ScriptOutcome.ERROR
        duration = time.monotonic() - start

        # Determine status (legacy compat).
        if outcome == ScriptOutcome.ERROR:
            status = VERIFY_FAIL
        elif exit_code == 0:
            status = VERIFY_PASS
        elif fail_on_nonzero:
            status = VERIFY_FAIL
        else:
            status = VERIFY_WARN

        cmd_result = PreAnalysisCommandResult(
            command_id=cmd_id,
            command=run_cmd,
            exit_code=exit_code,
            status=status,
            duration_seconds=duration,
            stdout=stdout,
            stderr=stderr,
            output_files=output_files,
            outcome=outcome,
        )
        result.command_results.append(cmd_result)

        # Write full log.
        log_path = log_dir / f"{cmd_id}.log"
        log_path.write_text(stdout + stderr, encoding="utf-8")

        # Write summary JSON.
        summary = {
            "schema_version": 1,
            "step_id": step_id,
            "command_id": cmd_id,
            "command": run_cmd,
            "exit_code": exit_code,
            "status": status,
            "duration_seconds": duration,
            "log_path": str(log_path),
            "output_files": output_files,
        }
        summary_path = log_dir / f"{cmd_id}.summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        cmd_result.summary_path = str(summary_path)

        if status == VERIFY_FAIL:
            result.failure_reason = (
                f"Pre-analysis command '{cmd_id}' failed with exit code {exit_code}."
            )
            break

    # Check tree modification.
    if working_dir is not None:
        after_git_snapshot = git_visible_snapshot(working_dir)
        if before_git_snapshot is not None and after_git_snapshot is not None:
            tree_changed = before_git_snapshot != after_git_snapshot
        else:
            after_fallback_snapshot = _filesystem_snapshot(working_dir, automation_dir)
            tree_changed = _fallback_tree_changed(
                before_fallback_snapshot,
                after_fallback_snapshot,
            )
        if tree_changed:
            result.tree_modified = True

    return result
