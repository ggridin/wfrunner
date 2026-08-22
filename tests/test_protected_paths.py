"""Agreement tests for protected-path classification."""

from __future__ import annotations

import pathlib

import pytest

from tests.helpers import make_implementation_step, make_plan
from tools.orchestrator.scope_enforcer import check_protected_files
from tools.plan_parser import parse_plan
from tools.plan_validator import validate_plan
from tools.protected_paths import is_protected_path


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
