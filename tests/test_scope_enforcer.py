"""Tests for scope enforcement — covers ALLOW-001 through ALLOW-006 and PROT-001 through PROT-004.

TDD: These tests are written before the implementation exists.
They define the expected behavior of the scope enforcer module.
"""

from __future__ import annotations

import pytest

from tests.helpers import (
    make_human_gate_step,
    make_implementation_step,
    make_plan,
)
from tools.constants import VIOLATION_PROTECTED_FILE
from tools.plan_parser import parse_plan
from tools.orchestrator.scope_enforcer import (
    check_allowed_files,
    check_protected_files,
)


TEST_PROTECTED_PATHS = (
    "schemas/",
    ".github/agents/",
    ".github/copilot-instructions.md",
    "prompts/",
    ".wfrunner/wfrunner.toml",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_steps(plan_text: str):
    """Parse a plan and return the list of parsed steps."""
    result = parse_plan(plan_text)
    assert result.ok, f"Plan parse errors: {result.errors}"
    return result.steps


# ===========================================================================
# ALLOW-001 through ALLOW-006: allowed_files enforcement
# ===========================================================================


# ---------------------------------------------------------------------------
# ALLOW-001: Existing allowed file modified → allowed
# ---------------------------------------------------------------------------


class TestALLOW001ExistingAllowedFileModified:
    """Modifying a file that is in allowed_files should be accepted."""

    def test_allowed_existing_file_modified(self) -> None:
        allowed_files = ["tools/__init__.py"]
        changed_files = {"tools/__init__.py": "modified"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 0

    def test_multiple_allowed_files_modified(self) -> None:
        allowed_files = ["tools/__init__.py", "tools/plan_parser.py"]
        changed_files = {
            "tools/__init__.py": "modified",
            "tools/plan_parser.py": "modified",
        }

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 0


# ---------------------------------------------------------------------------
# ALLOW-002: Listed non-existing file created → allowed
# ---------------------------------------------------------------------------


class TestALLOW002ListedNewFileCreated:
    """Creating a file that is in allowed_files should be accepted."""

    def test_allowed_new_file_created(self) -> None:
        allowed_files = ["tools/new_module.py"]
        changed_files = {"tools/new_module.py": "created"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 0

    def test_mix_of_created_and_modified(self) -> None:
        allowed_files = ["tools/__init__.py", "tools/new_module.py"]
        changed_files = {
            "tools/__init__.py": "modified",
            "tools/new_module.py": "created",
        }

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 0


# ---------------------------------------------------------------------------
# ALLOW-003: Unlisted file modified → scope violation
# ---------------------------------------------------------------------------


class TestALLOW003UnlistedFileModified:
    """Modifying a file NOT in allowed_files should be a scope violation."""

    def test_unlisted_file_modified(self) -> None:
        allowed_files = ["tools/__init__.py"]
        changed_files = {
            "tools/__init__.py": "modified",
            "tools/plan_parser.py": "modified",
        }

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 1
        assert violations[0].file_path == "tools/plan_parser.py"
        assert violations[0].reason == "not_in_allowed_files"

    def test_only_unlisted_file_modified(self) -> None:
        allowed_files = ["tools/__init__.py"]
        changed_files = {"tools/plan_parser.py": "modified"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 1
        assert violations[0].file_path == "tools/plan_parser.py"


# ---------------------------------------------------------------------------
# ALLOW-004: Unlisted file created → scope violation
# ---------------------------------------------------------------------------


class TestALLOW004UnlistedFileCreated:
    """Creating a file NOT in allowed_files should be a scope violation."""

    def test_unlisted_file_created(self) -> None:
        allowed_files = ["tools/__init__.py"]
        changed_files = {"tools/surprise.py": "created"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 1
        assert violations[0].file_path == "tools/surprise.py"
        assert violations[0].reason == "not_in_allowed_files"


# ---------------------------------------------------------------------------
# ALLOW-005: Listed file deleted → stop (deletion not allowed in Phase 1)
# ---------------------------------------------------------------------------


class TestALLOW005ListedFileDeleted:
    """Deleting a file listed in allowed_files is now permitted."""

    def test_listed_file_deleted(self) -> None:
        allowed_files = ["tools/__init__.py"]
        changed_files = {"tools/__init__.py": "deleted"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 0

    def test_unlisted_file_deleted(self) -> None:
        allowed_files = ["tools/__init__.py"]
        changed_files = {"tools/other.py": "deleted"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) >= 1
        deleted_violations = [v for v in violations if v.file_path == "tools/other.py"]
        assert len(deleted_violations) >= 1


# ---------------------------------------------------------------------------
# ALLOW-006: File renamed → stop
# ---------------------------------------------------------------------------


class TestALLOW006FileRenamed:
    """File renames are now allowed when the file is in allowed_files."""

    def test_file_renamed(self) -> None:
        allowed_files = ["tools/__init__.py"]
        changed_files = {"tools/__init__.py": "renamed"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 0

    def test_unlisted_file_renamed(self) -> None:
        allowed_files = ["tools/__init__.py"]
        changed_files = {"tools/old_name.py": "renamed"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) >= 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestAllowedFilesEdgeCases:
    """Additional coverage for edge conditions."""

    def test_no_changed_files(self) -> None:
        allowed_files = ["tools/__init__.py"]
        changed_files: dict[str, str] = {}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 0

    def test_empty_allowed_files_with_changes(self) -> None:
        allowed_files: list[str] = []
        changed_files = {"tools/__init__.py": "modified"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 1

    def test_multiple_violations_reported(self) -> None:
        allowed_files = ["tools/__init__.py"]
        changed_files = {
            "tools/__init__.py": "modified",
            "tools/surprise1.py": "created",
            "tools/surprise2.py": "modified",
        }

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 2
        violation_paths = {v.file_path for v in violations}
        assert "tools/surprise1.py" in violation_paths
        assert "tools/surprise2.py" in violation_paths


# ---------------------------------------------------------------------------
# Folder pattern support
# ---------------------------------------------------------------------------


class TestAllowedFilesFolderPatterns:
    """Folder patterns distinguish direct children from recursive descendants."""

    def test_exact_file_path_match_still_works(self) -> None:
        allowed_files = ["tools/config.py"]
        changed_files = {"tools/config.py": "modified"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 0

    def test_folder_pattern_allows_file_under_prefix(self) -> None:
        allowed_files = ["tests/*"]
        changed_files = {"tests/test_foo.py": "created"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 0

    def test_recursive_folder_pattern_allows_direct_and_nested_files(self) -> None:
        allowed_files = ["docs/**"]
        changed_files = {
            "docs/a.md": "modified",
            "docs/a/b/c/deep.md": "modified",
        }

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 0

    def test_single_level_folder_pattern_rejects_nested_file(self) -> None:
        allowed_files = ["docs/*"]
        changed_files = {"docs/a/b/c/deep.md": "modified"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 1
        assert violations[0].file_path == "docs/a/b/c/deep.md"
        assert violations[0].reason == "not_in_allowed_files"

    def test_folder_pattern_rejects_different_prefix(self) -> None:
        allowed_files = ["tests/*"]
        changed_files = {"tools/config.py": "modified"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 1
        assert violations[0].file_path == "tools/config.py"
        assert violations[0].reason == "not_in_allowed_files"

    def test_nested_folder_pattern_allows_file_under_prefix(self) -> None:
        allowed_files = ["tools/orchestrator/*"]
        changed_files = {"tools/orchestrator/new_module.py": "created"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 0

    def test_nested_folder_pattern_rejects_sibling_file(self) -> None:
        allowed_files = ["tools/orchestrator/*"]
        changed_files = {"tools/config.py": "modified"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 1
        assert violations[0].file_path == "tools/config.py"
        assert violations[0].reason == "not_in_allowed_files"

    def test_mixed_exact_files_and_folder_patterns(self) -> None:
        allowed_files = ["tools/config.py", "tests/**"]
        changed_files = {
            "tools/config.py": "modified",
            "tests/test_foo.py": "created",
            "tests/sub/deep.py": "modified",
        }

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 0

    def test_deletion_allowed_when_folder_pattern_matches(self) -> None:
        allowed_files = ["tests/*"]
        changed_files = {"tests/test_foo.py": "deleted"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 0

    def test_rename_allowed_when_folder_pattern_matches(self) -> None:
        allowed_files = ["tests/*"]
        changed_files = {"tests/test_foo.py": "renamed"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 0

    def test_protected_file_detection_works_with_folder_patterns(self) -> None:
        plan = make_plan(
            make_implementation_step(
                step_id="STEP-001",
                title="Update schemas",
                allowed_files=["schemas/*"],
            ),
        )
        steps = _parse_steps(plan)

        result = check_protected_files(
            step=steps[0],
            step_index=0,
            all_steps=steps,
            protected_paths=TEST_PROTECTED_PATHS,
        )

        assert not result.ok
        assert any(v.file_path == "schemas/*" for v in result.violations)


# ===========================================================================
# PROT-001 through PROT-004: Protected-file enforcement at orchestrator level
# ===========================================================================


# ---------------------------------------------------------------------------
# PROT-001: Modifies protected file without prior HUMAN_GATE → blocks
# ---------------------------------------------------------------------------


class TestProtectedPathsRequireExplicitConfig:
    """Protected path checks must not fall back to hidden defaults."""

    @pytest.mark.parametrize("step_type", ["IMPLEMENTATION", "HUMAN_GATE"])
    def test_omitted_protected_paths_raises_for_every_step_type(
        self,
        step_type: str,
    ) -> None:
        if step_type == "IMPLEMENTATION":
            step_text = make_implementation_step(
                step_id="STEP-001",
                title="Update agents",
                allowed_files=[".github/agents/spec-implementer.md"],
            )
        else:
            step_text = make_human_gate_step(
                step_id="STEP-001",
                title="Review protected changes",
            )

        plan = make_plan(step_text)
        steps = _parse_steps(plan)

        with pytest.raises(TypeError):
            check_protected_files(
                step=steps[0],
                step_index=0,
                all_steps=steps,
            )


class TestPROT001NoGateBeforeProtectedFile:
    """Step modifies a protected path without a preceding HUMAN_GATE."""

    def test_modifies_run_plan_without_gate(self) -> None:
        plan = make_plan(
            make_implementation_step(
                step_id="STEP-001",
                title="Modify run_plan",
                allowed_files=["schemas/implementation-step.schema.json"],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]

        result = check_protected_files(
            step=step,
            step_index=0,
            all_steps=steps,
            protected_paths=TEST_PROTECTED_PATHS,
        )

        assert not result.ok
        assert any("schemas/implementation-step.schema.json" in v.file_path for v in result.violations)
        assert all(v.reason == VIOLATION_PROTECTED_FILE for v in result.violations)

    def test_modifies_agents_without_gate(self) -> None:
        plan = make_plan(
            make_implementation_step(
                step_id="STEP-001",
                title="Modify agents",
                allowed_files=[".github/agents/spec-implementer.md"],
            ),
        )
        steps = _parse_steps(plan)

        result = check_protected_files(
            step=steps[0],
            step_index=0,
            all_steps=steps,
            protected_paths=TEST_PROTECTED_PATHS,
        )

        assert not result.ok


# ---------------------------------------------------------------------------
# PROT-002: Modifies protected file after immediately preceding HUMAN_GATE → ok
# ---------------------------------------------------------------------------


class TestPROT002GateImmediatelyBefore:
    """Protected-file change allowed when immediately preceded by HUMAN_GATE."""

    def test_gate_immediately_before_allows_schema_change(self) -> None:
        plan = make_plan(
            make_human_gate_step(
                step_id="STEP-001",
                title="Review schema change",
            ),
            make_implementation_step(
                step_id="STEP-002",
                title="Update schema",
                allowed_files=["schemas/implementation-step.schema.json"],
            ),
        )
        steps = _parse_steps(plan)

        result = check_protected_files(
            step=steps[1],
            step_index=1,
            all_steps=steps,
            protected_paths=TEST_PROTECTED_PATHS,
        )

        assert result.ok

    def test_gate_immediately_before_allows_prompt_change(self) -> None:
        plan = make_plan(
            make_human_gate_step(
                step_id="STEP-001",
                title="Review prompt change",
            ),
            make_implementation_step(
                step_id="STEP-002",
                title="Update prompt",
                allowed_files=["prompts/implement-step.md"],
            ),
        )
        steps = _parse_steps(plan)

        result = check_protected_files(
            step=steps[1],
            step_index=1,
            all_steps=steps,
            protected_paths=TEST_PROTECTED_PATHS,
        )

        assert result.ok


# ---------------------------------------------------------------------------
# PROT-003: Modifies .github/agents/ without prior HUMAN_GATE → blocks
# ---------------------------------------------------------------------------


class TestPROT003AgentsWithoutGate:
    """Step modifies .github/agents/ without any prior HUMAN_GATE."""

    def test_blocks_agents_modification(self) -> None:
        plan = make_plan(
            make_implementation_step(
                step_id="STEP-001",
                title="Some work",
                allowed_files=["tools/__init__.py"],
            ),
            make_implementation_step(
                step_id="STEP-002",
                title="Modify agents",
                allowed_files=[".github/agents/spec-fixer.md"],
            ),
        )
        steps = _parse_steps(plan)

        result = check_protected_files(
            step=steps[1],
            step_index=1,
            all_steps=steps,
            protected_paths=TEST_PROTECTED_PATHS,
        )

        assert not result.ok


# ---------------------------------------------------------------------------
# PROT-004: Prior gate exists but is NOT immediately before → blocks
# ---------------------------------------------------------------------------


class TestPROT004GateNotImmediatelyBefore:
    """A HUMAN_GATE exists in the plan but is not the immediately preceding step."""

    def test_gate_two_steps_before_blocks(self) -> None:
        plan = make_plan(
            make_human_gate_step(
                step_id="STEP-001",
                title="Review",
            ),
            make_implementation_step(
                step_id="STEP-002",
                title="Normal work",
                allowed_files=["tools/__init__.py"],
            ),
            make_implementation_step(
                step_id="STEP-003",
                title="Protected change",
                allowed_files=["schemas/new.schema.json"],
            ),
        )
        steps = _parse_steps(plan)

        result = check_protected_files(
            step=steps[2],
            step_index=2,
            all_steps=steps,
            protected_paths=TEST_PROTECTED_PATHS,
        )

        assert not result.ok
        assert any("schemas/" in v.file_path for v in result.violations)

    def test_gate_far_before_blocks(self) -> None:
        plan = make_plan(
            make_human_gate_step(step_id="STEP-001", title="Early review"),
            make_implementation_step(
                step_id="STEP-002", title="Work A",
                allowed_files=["tools/__init__.py"],
            ),
            make_implementation_step(
                step_id="STEP-003", title="Work B",
                allowed_files=["tools/__init__.py"],
            ),
            make_implementation_step(
                step_id="STEP-004",
                title="Late protected change",
                allowed_files=["prompts/implement-step.md"],
            ),
        )
        steps = _parse_steps(plan)

        result = check_protected_files(
            step=steps[3],
            step_index=3,
            all_steps=steps,
            protected_paths=TEST_PROTECTED_PATHS,
        )

        assert not result.ok


# ---------------------------------------------------------------------------
# Protected-file edge cases
# ---------------------------------------------------------------------------


class TestProtectedFilesEdgeCases:
    """Additional coverage for protected-file rule edge cases."""

    def test_non_protected_files_always_ok(self) -> None:
        plan = make_plan(
            make_implementation_step(
                step_id="STEP-001",
                title="Normal work",
                allowed_files=["tools/__init__.py", "tests/test_foo.py"],
            ),
        )
        steps = _parse_steps(plan)

        result = check_protected_files(
            step=steps[0],
            step_index=0,
            all_steps=steps,
            protected_paths=TEST_PROTECTED_PATHS,
        )

        assert result.ok

    def test_human_gate_step_always_ok(self) -> None:
        """HUMAN_GATE steps don't modify files, so they pass protected check."""
        plan = make_plan(
            make_human_gate_step(step_id="STEP-001", title="Review"),
        )
        steps = _parse_steps(plan)

        result = check_protected_files(
            step=steps[0],
            step_index=0,
            all_steps=steps,
            protected_paths=TEST_PROTECTED_PATHS,
        )

        assert result.ok

    def test_copilot_instructions_requires_gate(self) -> None:
        plan = make_plan(
            make_implementation_step(
                step_id="STEP-001",
                title="Update instructions",
                allowed_files=[".github/copilot-instructions.md"],
            ),
        )
        steps = _parse_steps(plan)

        result = check_protected_files(
            step=steps[0],
            step_index=0,
            all_steps=steps,
            protected_paths=TEST_PROTECTED_PATHS,
        )

        assert not result.ok

    def test_mixed_protected_and_non_protected(self) -> None:
        """If allowed_files contains both protected and non-protected files,
        the protected file still requires a gate."""
        plan = make_plan(
            make_implementation_step(
                step_id="STEP-001",
                title="Mixed files",
                allowed_files=["tools/__init__.py", "schemas/new.json"],
            ),
        )
        steps = _parse_steps(plan)

        result = check_protected_files(
            step=steps[0],
            step_index=0,
            all_steps=steps,
            protected_paths=TEST_PROTECTED_PATHS,
        )

        assert not result.ok


# ===========================================================================
# ALLOW-007 and ALLOW-008: New deletion behavior (TDD for STEP-017)
# ===========================================================================


# ---------------------------------------------------------------------------
# ALLOW-007: Listed file deleted → allowed (new behavior)
# ---------------------------------------------------------------------------


class TestALLOW007ListedFileDeletedAllowed:
    """Deleting a file listed in allowed_files should produce no violation."""

    def test_listed_file_deleted_no_violation(self) -> None:
        allowed_files = ["tools/__init__.py"]
        changed_files = {"tools/__init__.py": "deleted"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 0

    def test_listed_file_deleted_with_folder_pattern(self) -> None:
        allowed_files = ["tests/*"]
        changed_files = {"tests/test_foo.py": "deleted"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 0


# ---------------------------------------------------------------------------
# ALLOW-008: Unlisted file deleted → VIOLATION_NOT_IN_ALLOWED (new behavior)
# ---------------------------------------------------------------------------


class TestALLOW008UnlistedFileDeletedViolation:
    """Deleting a file NOT in allowed_files should produce a not_in_allowed_files violation."""

    def test_unlisted_file_deleted_is_violation(self) -> None:
        allowed_files = ["tools/__init__.py"]
        changed_files = {"tools/other.py": "deleted"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 1
        assert violations[0].file_path == "tools/other.py"
        assert violations[0].reason == "not_in_allowed_files"

    def test_empty_allowed_files_deletion_is_violation(self) -> None:
        allowed_files: list[str] = []
        changed_files = {"tools/any.py": "deleted"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 1
        assert violations[0].reason == "not_in_allowed_files"


# ===========================================================================
# ALLOW-009 and ALLOW-010: New renaming behavior (TDD for STEP-017)
# ===========================================================================


# ---------------------------------------------------------------------------
# ALLOW-009: Renamed file destination in allowed_files → allowed (new behavior)
# ---------------------------------------------------------------------------


class TestALLOW009RenamedFileDestinationAllowed:
    """Renaming a file whose destination path is in allowed_files produces no violation."""

    def test_renamed_destination_in_allowed_no_violation(self) -> None:
        allowed_files = ["tools/new_name.py"]
        changed_files = {"tools/new_name.py": "renamed"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 0

    def test_renamed_destination_with_folder_pattern_no_violation(self) -> None:
        allowed_files = ["tests/*"]
        changed_files = {"tests/new_test.py": "renamed"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 0


# ---------------------------------------------------------------------------
# ALLOW-010: Renamed file destination NOT in allowed_files → violation (new behavior)
# ---------------------------------------------------------------------------


class TestALLOW010RenamedFileDestinationNotAllowed:
    """Renaming a file whose destination is NOT in allowed_files produces a violation."""

    def test_renamed_destination_not_in_allowed(self) -> None:
        allowed_files = ["tools/__init__.py"]
        changed_files = {"tools/unlisted_new.py": "renamed"}

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 1
        assert violations[0].file_path == "tools/unlisted_new.py"
        assert violations[0].reason == "not_in_allowed_files"

    def test_renamed_alongside_allowed_modified_file(self) -> None:
        allowed_files = ["tools/__init__.py"]
        changed_files = {
            "tools/__init__.py": "modified",
            "tools/unlisted_new.py": "renamed",
        }

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 1
        assert violations[0].file_path == "tools/unlisted_new.py"
        assert violations[0].reason == "not_in_allowed_files"


# ===========================================================================
# Integration: GitChangeDetector rename output through check_allowed_files
# ===========================================================================


class TestRenameDetectorEnforcerIntegration:
    """Wire GitChangeDetector rename representation through check_allowed_files."""

    def test_rename_allowed_when_both_source_and_destination_in_allowed_files(
        self,
    ) -> None:
        # Simulated GitChangeDetector output for a rename.
        changed_files = {"old.py": "deleted", "new.py": "renamed"}
        allowed_files = ["old.py", "new.py"]

        violations = check_allowed_files(allowed_files, changed_files)

        assert violations == []

    def test_rename_rejected_when_source_not_in_allowed_files(self) -> None:
        changed_files = {"old.py": "deleted", "new.py": "renamed"}
        allowed_files = ["new.py"]

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 1
        assert violations[0].file_path == "old.py"

    def test_rename_rejected_when_destination_not_in_allowed_files(self) -> None:
        changed_files = {"old.py": "deleted", "new.py": "renamed"}
        allowed_files = ["old.py"]

        violations = check_allowed_files(allowed_files, changed_files)

        assert len(violations) == 1
        assert violations[0].file_path == "new.py"
