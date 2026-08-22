"""Scope enforcer — enforces allowed_files and protected-file rules."""

from __future__ import annotations

from dataclasses import dataclass, field

from tools.constants import (
    FIELD_ALLOWED_FILES,
    FIELD_TYPE,
    STEP_TYPE_HUMAN_GATE,
    VIOLATION_NOT_IN_ALLOWED,
    VIOLATION_PROTECTED_FILE,
)
from tools.plan_parser import ParsedStep
from tools.protected_paths import is_protected_path


@dataclass
class ScopeViolation:
    """A single scope violation detected after agent execution."""

    file_path: str
    reason: str


@dataclass
class ProtectedFileResult:
    """Result of checking protected-file rules for a step."""

    violations: list[ScopeViolation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.violations) == 0


def _is_allowed(file_path: str, allowed_files: list[str]) -> bool:
    """Return True if *file_path* matches an exact allowed path or folder pattern."""
    if file_path in set(allowed_files):
        return True

    for allowed_file in allowed_files:
        if allowed_file.endswith("/**"):
            prefix = allowed_file[:-2]
            if file_path.startswith(prefix):
                return True
        elif allowed_file.endswith("/*"):
            prefix = allowed_file[:-1]
            relative_path = file_path.removeprefix(prefix)
            if relative_path != file_path and "/" not in relative_path:
                return True

    return False


def check_allowed_files(
    allowed_files: list[str],
    changed_files: dict[str, str],
) -> list[ScopeViolation]:
    """Check changed files against the step's allowed_files list.

    Args:
        allowed_files: Repository-relative file paths the step may modify/create.
        changed_files: Dict mapping file paths to change type
            (``"modified"``, ``"created"``, ``"deleted"``, ``"renamed"``).

    Returns:
        A list of ScopeViolation for any disallowed changes.
    """
    violations: list[ScopeViolation] = []

    for file_path, _change_type in changed_files.items():
        if not _is_allowed(file_path, allowed_files):
            violations.append(ScopeViolation(file_path=file_path, reason=VIOLATION_NOT_IN_ALLOWED))

    return violations


def check_protected_files(
    step: ParsedStep,
    step_index: int,
    all_steps: list[ParsedStep],
    *,
    protected_paths: list[str] | tuple[str, ...],
) -> ProtectedFileResult:
    """Check whether a step's allowed_files touch protected paths
    and whether the immediately preceding step is a HUMAN_GATE.

    Args:
        step: The step being checked.
        step_index: The index of this step in the plan.
        all_steps: All parsed steps in document order.

    Returns:
        A ProtectedFileResult with any violations found.
    """
    result = ProtectedFileResult()

    # HUMAN_GATE steps don't modify files — always ok.
    if step.yaml_block.get(FIELD_TYPE) == STEP_TYPE_HUMAN_GATE:
        return result

    allowed_files = step.yaml_block.get(FIELD_ALLOWED_FILES, [])
    protected_in_step = [f for f in allowed_files if is_protected_path(f, protected_paths)]

    if not protected_in_step:
        return result

    # Check if the immediately preceding step is a HUMAN_GATE.
    has_gate = False
    if step_index > 0:
        prev_step = all_steps[step_index - 1]
        if prev_step.yaml_block.get(FIELD_TYPE) == STEP_TYPE_HUMAN_GATE:
            has_gate = True

    if not has_gate:
        for f in protected_in_step:
            result.violations.append(
                ScopeViolation(file_path=f, reason=VIOLATION_PROTECTED_FILE)
            )

    return result
