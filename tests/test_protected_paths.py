"""Agreement tests for protected-path classification."""

from __future__ import annotations

import pathlib

import pytest

from tests.helpers import make_implementation_step, make_plan
from tools.orchestrator.scope_enforcer import check_protected_files
from tools.plan_parser import parse_plan
from tools.plan_validator import validate_plan
from tools.protected_paths import allowed_entry_covers_protected_path, is_protected_path


PROTECTED_PATHS = (
    "tools/run_plan.py",
    "schemas",
    "prompts/",
    ".github/agents/",
)


@pytest.mark.parametrize(
    ("file_path", "expected"),
    [
        ("tools/run_plan.py", True),
        ("prompts/system_prompt.implementation.md", True),
        ("schemas/implementation-step.schema.json", True),
        (".github/agents/review/code-review.md", True),
        ("tools/run_plan.py.bak", False),
        ("schemas_extra/x.json", False),
    ],
)
def test_validation_and_enforcement_agree(
    file_path: str,
    expected: bool,
) -> None:
    parse_result = parse_plan(
        make_plan(
            make_implementation_step(
                step_id="STEP-001",
                title="Check protected path",
                allowed_files=[file_path],
            ),
        )
    )
    assert parse_result.ok

    validation_result = validate_plan(
        parse_result,
        schemas_dir=pathlib.Path(__file__).resolve().parent.parent / "schemas",
        protected_paths=PROTECTED_PATHS,
    )
    enforcement_result = check_protected_files(
        step=parse_result.steps[0],
        step_index=0,
        all_steps=parse_result.steps,
        protected_paths=PROTECTED_PATHS,
    )

    assert (not validation_result.ok) is expected
    assert (not enforcement_result.ok) is expected


@pytest.mark.parametrize(
    ("file_path", "protected_paths", "expected"),
    [
        (r"schemas\step.json", ("schemas\\",), True),
        (r"tools\run_plan.py", ("tools/run_plan.py",), True),
        ("tools/run_plan.py.bak", ("tools/run_plan.py",), False),
        ("schemas_extra/x.json", ("schemas",), False),
    ],
)
def test_is_protected_path_normalizes_separators(
    file_path: str,
    protected_paths: tuple[str, ...],
    expected: bool,
) -> None:
    assert is_protected_path(file_path, protected_paths) is expected


@pytest.mark.parametrize(
    ("allowed_entry", "expected"),
    [
        # Recursive patterns reach every protected entry below the prefix.
        (".github/**", True),
        ("tools/**", True),
        ("schemas/**", True),
        # Single-level patterns reach protected entries directly inside.
        ("tools/*", True),
        ("prompts/*", True),
        # A single-level pattern does not reach a protected subdirectory.
        (".github/workflows/*", False),
        # Unrelated scopes stay allowed.
        ("tests/**", False),
        ("docs/*", False),
        ("src/app.py", False),
    ],
)
def test_wildcard_entries_that_cover_protected_paths_are_detected(
    allowed_entry: str,
    expected: bool,
) -> None:
    assert allowed_entry_covers_protected_path(allowed_entry, PROTECTED_PATHS) is expected


@pytest.mark.parametrize("allowed_entry", [".github/**", "tools/*"])
def test_wildcard_entries_require_a_gate_in_validation_and_enforcement(
    allowed_entry: str,
) -> None:
    """A broad pattern must not smuggle protected writes past either gate."""
    parse_result = parse_plan(
        make_plan(
            make_implementation_step(
                step_id="STEP-001",
                title="Broad scope",
                allowed_files=[allowed_entry],
            ),
        )
    )
    assert parse_result.ok

    validation_result = validate_plan(
        parse_result,
        schemas_dir=pathlib.Path(__file__).resolve().parent.parent / "schemas",
        protected_paths=PROTECTED_PATHS,
    )
    enforcement_result = check_protected_files(
        step=parse_result.steps[0],
        step_index=0,
        all_steps=parse_result.steps,
        protected_paths=PROTECTED_PATHS,
    )

    assert not validation_result.ok
    assert not enforcement_result.ok
