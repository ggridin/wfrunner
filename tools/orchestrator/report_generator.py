"""Report generator — produces .automation/whole-plan-report.md."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.constants import (
    FAILURE_HUMAN_GATE,
    FR_CODE,
    PROGRESS_FIELD_COMMIT,
    PROGRESS_FIELD_FAILURE_REASON,
    PROGRESS_FIELD_STEPS,
    PROGRESS_FIELD_STATE,
    STATE_BLOCKED,
    STATE_DONE,
    STATE_FAILED,
)


def generate_whole_plan_report(
    report_path: Path,
    progress: dict[str, Any],
    stop_reason: str | None = None,
) -> None:
    """Generate a whole-plan report from the current progress state.

    Args:
        report_path: Path to write the whole-plan-report.md.
        progress: The current progress dict.
        stop_reason: Optional top-level stop reason (e.g. "MAX_STEPS_REACHED").
    """
    report_path.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# Whole-Plan Report\n\n"]

    steps = progress.get(PROGRESS_FIELD_STEPS, {})
    done = [sid for sid, s in steps.items() if s[PROGRESS_FIELD_STATE] == STATE_DONE]
    failed = [sid for sid, s in steps.items() if s[PROGRESS_FIELD_STATE] == STATE_FAILED]
    blocked = [sid for sid, s in steps.items() if s[PROGRESS_FIELD_STATE] == STATE_BLOCKED]

    lines.append("## Summary\n\n")
    lines.append(f"- Completed: {len(done)}\n")
    lines.append(f"- Failed: {len(failed)}\n")
    lines.append(f"- Blocked: {len(blocked)}\n")

    if stop_reason:
        lines.append(f"- Stop reason: {stop_reason}\n")

    if done:
        lines.append("\n## Completed Steps\n\n")
        for sid in done:
            commit = steps[sid].get(PROGRESS_FIELD_COMMIT)
            commit_str = f" (commit: {commit})" if commit else ""
            lines.append(f"- {sid}{commit_str}\n")

    if failed:
        lines.append("\n## Failed Steps\n\n")
        for sid in failed:
            fr = steps[sid].get(PROGRESS_FIELD_FAILURE_REASON, {})
            code = fr.get(FR_CODE, "UNKNOWN") if fr else "UNKNOWN"
            lines.append(f"- {sid}: {code}\n")

    if blocked:
        lines.append("\n## Blocked Steps\n\n")
        for sid in blocked:
            fr = steps[sid].get(PROGRESS_FIELD_FAILURE_REASON, {})
            code = fr.get(FR_CODE, "UNKNOWN") if fr else "UNKNOWN"
            msg = fr.get("message", "") if fr else ""
            lines.append(f"- {sid}: {code} — {msg}\n")

    lines.append("\n## Next Action\n\n")
    if blocked:
        for sid in blocked:
            fr = steps[sid].get(PROGRESS_FIELD_FAILURE_REASON, {})
            if fr and fr.get(FR_CODE) == FAILURE_HUMAN_GATE:
                lines.append(f"Human review required at {sid}.\n")
    elif failed:
        lines.append("Investigate failed steps before resuming.\n")
    else:
        lines.append("All steps completed successfully.\n")

    report_path.write_text("".join(lines), encoding="utf-8")
