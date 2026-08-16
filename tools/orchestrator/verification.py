"""Verification runner — executes verification commands after agent work."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.plan_parser import ParsedStep
from tools.constants import (
    FIELD_COMMANDS,
    FIELD_ID,
    FIELD_VERIFICATION,
    ScriptOutcome,
    VERIFY_FAIL,
    VERIFY_PASS,
    VERIFY_TIMEOUT,
)

_TAIL_MAX_CHARS = 4096


@dataclass
class VerificationCommandResult:
    """Result of a single verification command execution."""

    command_index: int
    command: str
    exit_code: int
    status: str  # "PASS", "FAIL", "TIMEOUT"
    duration_seconds: float
    stdout_tail: str
    stderr_tail: str
    log_path: str
    outcome: ScriptOutcome = ScriptOutcome.PASS


@dataclass
class VerificationResult:
    """Aggregate result of all verification commands for an attempt."""

    command_results: list[VerificationCommandResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        if not self.command_results:
            return True
        return all(cr.outcome == ScriptOutcome.PASS for cr in self.command_results)


def run_verification(
    step: ParsedStep,
    *,
    automation_dir: Path,
    attempt: int,
    timeout_seconds: float | None = None,
) -> VerificationResult:
    """Run verification commands for a step.

    Args:
        step: The parsed step containing verification metadata.
        automation_dir: Path to the .automation directory.
        attempt: The attempt number (1-based).
        timeout_seconds: Per-command timeout in seconds. None means no timeout.

    Returns:
        A VerificationResult with per-command outcomes.
    """
    result = VerificationResult()

    verification = step.yaml_block.get(FIELD_VERIFICATION, {})
    if verification is None:
        return result

    commands = verification.get(FIELD_COMMANDS, [])
    if not commands:
        return result

    step_id = step.yaml_block[FIELD_ID]
    log_dir = automation_dir / "verification" / step_id
    log_dir.mkdir(parents=True, exist_ok=True)

    for idx, cmd in enumerate(commands):
        log_filename = f"attempt-{attempt}-command-{idx}.log"
        log_path = log_dir / log_filename

        start = time.monotonic()
        timed_out = False
        outcome = ScriptOutcome.PASS

        # Use Popen so we can kill the entire process tree on timeout.
        # On Windows, CREATE_NEW_PROCESS_GROUP lets us kill the whole tree.
        popen_kwargs: dict[str, Any] = dict(
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            proc = subprocess.Popen(cmd, **popen_kwargs)
            try:
                stdout, stderr = proc.communicate(timeout=timeout_seconds)
                exit_code = proc.returncode
                if exit_code == 0:
                    outcome = ScriptOutcome.PASS
                else:
                    outcome = ScriptOutcome.FAIL
            except subprocess.TimeoutExpired:
                # Kill the process tree, not just the shell.
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        proc.kill()
                proc.wait()
                timed_out = True
                exit_code = -1
                stdout = ""
                stderr = ""
                outcome = ScriptOutcome.ERROR
        except (FileNotFoundError, OSError):
            timed_out = False
            exit_code = -1
            stdout = ""
            stderr = ""
            outcome = ScriptOutcome.ERROR
        duration = time.monotonic() - start

        if timed_out:
            status = VERIFY_TIMEOUT
        elif exit_code == 0:
            status = VERIFY_PASS
        else:
            status = VERIFY_FAIL

        # Write full log.
        full_log = stdout + stderr
        log_path.write_text(full_log, encoding="utf-8")

        # Bounded excerpts for summaries.
        stdout_tail = stdout[-_TAIL_MAX_CHARS:] if len(stdout) > _TAIL_MAX_CHARS else stdout
        stderr_tail = stderr[-_TAIL_MAX_CHARS:] if len(stderr) > _TAIL_MAX_CHARS else stderr

        cmd_result = VerificationCommandResult(
            command_index=idx,
            command=cmd,
            exit_code=exit_code,
            status=status,
            duration_seconds=duration,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            log_path=str(log_path),
            outcome=outcome,
        )
        result.command_results.append(cmd_result)

        # Write summary JSON.
        summary: dict[str, Any] = {
            "schema_version": 1,
            "step_id": step_id,
            "attempt": attempt,
            "command_index": idx,
            "command": cmd,
            "exit_code": exit_code,
            "status": status,
            "duration_seconds": duration,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "log_path": str(log_path),
        }
        summary_path = log_dir / f"attempt-{attempt}-command-{idx}.summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        # Stop at first failure or timeout.
        if status != VERIFY_PASS:
            break

    return result
