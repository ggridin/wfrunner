"""Run logger — appends per-step entries to .automation/run-log.md."""

from __future__ import annotations

from pathlib import Path


def append_log_entry(
    log_path: Path,
    step_id: str,
    agent: str | None,
    verification_status: str | None,
    stop_reason: str | None = None,
) -> None:
    """Append a run-log entry for a single step.

    Args:
        log_path: Path to the run-log.md file.
        step_id: The step ID.
        agent: The agent used (or None for HUMAN_GATE).
        verification_status: "PASS", "FAIL", or None.
        stop_reason: Optional stop reason string.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"## {step_id}\n"]
    if agent:
        lines.append(f"- **Agent**: {agent}\n")
    if verification_status:
        lines.append(f"- **Verification**: {verification_status}\n")
    if stop_reason:
        lines.append(f"- **Stop reason**: {stop_reason}\n")
    lines.append("\n")

    with log_path.open("a", encoding="utf-8") as f:
        f.writelines(lines)
