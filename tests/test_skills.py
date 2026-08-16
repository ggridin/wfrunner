"""Tests for project-level Copilot skill artifacts."""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / ".github" / "skills"

EXPECTED_REFERENCES: dict[str, tuple[str, ...]] = {
    "python-developer": (
        "code-conventions.md",
        "error-handling.md",
        "anti-patterns.md",
        "project-structure.md",
    ),
    "wfrunner-planner": (
        "plan-format.md",
        "plan-modification.md",
        "wfrunner-conventions.md",
    ),
    "wfrunner-docs": (
        "doc-hierarchy.md",
        "review-checklist.md",
        "glossary.md",
    ),
}

EXPECTED_DOCS_HIERARCHY = (
    "WaterfallRunner_architecture.md",
    "WaterfallRunner_decisions.md",
    "WaterfallRunner_agent_design.md",
    "Phase1_architecture.md",
    "Phase1_design.md",
    "Phase1_contracts.md",
    "Phase1_operations.md",
    "Phase1_test_scenarios.md",
)


def _skill_path(skill_name: str) -> Path:
    return SKILLS_ROOT / skill_name


def _skill_markdown_path(skill_name: str) -> Path:
    return _skill_path(skill_name) / "SKILL.md"


def _references_path(skill_name: str) -> Path:
    return _skill_path(skill_name) / "references"


def _read_text(path: Path) -> str:
    assert path.exists(), f"Expected file to exist: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def _read_skill_frontmatter(skill_name: str) -> dict[str, Any]:
    skill_file = _skill_markdown_path(skill_name)
    lines = _read_text(skill_file).splitlines()

    assert lines, f"{skill_file.relative_to(ROOT)} is empty"
    assert lines[0] == "---", f"{skill_file.relative_to(ROOT)} must start with YAML frontmatter"
    assert "---" in lines[1:], f"{skill_file.relative_to(ROOT)} must close YAML frontmatter"

    end_index = lines.index("---", 1)
    frontmatter = "\n".join(lines[1:end_index])
    parsed = yaml.safe_load(frontmatter)

    assert isinstance(parsed, dict), f"{skill_file.relative_to(ROOT)} frontmatter must be a mapping"
    return parsed


def _assert_exact_reference_docs(skill_name: str) -> None:
    references_dir = _references_path(skill_name)
    assert references_dir.is_dir(), f"Expected directory to exist: {references_dir.relative_to(ROOT)}"

    actual = sorted(path.name for path in references_dir.iterdir())
    expected = sorted(EXPECTED_REFERENCES[skill_name])
    assert actual == expected


def _all_markdown_text(skill_name: str) -> str:
    files = [_skill_markdown_path(skill_name)]
    files.extend(_references_path(skill_name) / name for name in EXPECTED_REFERENCES[skill_name])
    return "\n".join(_read_text(path) for path in files)


def _renumber_script_path() -> Path:
    return _skill_path("wfrunner-planner") / "scripts" / "renumber_steps.py"


@pytest.mark.parametrize(
    "skill_name",
    tuple(EXPECTED_REFERENCES),
    ids=lambda skill_name: skill_name.replace("-", "_"),
)
def test_skill_frontmatter_exists_and_matches_folder(skill_name: str) -> None:
    frontmatter = _read_skill_frontmatter(skill_name)

    assert frontmatter.get("name") == skill_name
    description = frontmatter.get("description")
    assert isinstance(description, str)
    assert description.strip()
    assert len(description) < 1024


@pytest.mark.parametrize(
    "skill_name",
    tuple(EXPECTED_REFERENCES),
    ids=lambda skill_name: skill_name.replace("-", "_"),
)
def test_core_skill_markdown_stays_under_200_lines(skill_name: str) -> None:
    lines = _read_text(_skill_markdown_path(skill_name)).splitlines()

    assert len(lines) < 200


REFERENCE_CASES = [
    (skill_name, reference_name)
    for skill_name, reference_names in EXPECTED_REFERENCES.items()
    for reference_name in reference_names
]


@pytest.mark.parametrize(
    ("skill_name", "reference_name"),
    REFERENCE_CASES,
    ids=[
        f"{skill_name.replace('-', '_')}_{reference_name.removesuffix('.md').replace('-', '_')}"
        for skill_name, reference_name in REFERENCE_CASES
    ],
)
def test_reference_documents_stay_under_500_lines(skill_name: str, reference_name: str) -> None:
    lines = _read_text(_references_path(skill_name) / reference_name).splitlines()

    assert len(lines) < 500


class TestPythonDeveloperSkill:
    def test_python_developer_has_exactly_requested_reference_docs(self) -> None:
        _assert_exact_reference_docs("python-developer")

    def test_python_developer_references_real_project_test_helpers(self) -> None:
        skill_text = _all_markdown_text("python-developer")

        for relative_path in (
            "tests/helpers.py",
            "tests/conftest.py",
            "tests/fake_agent.py",
        ):
            assert (ROOT / relative_path).is_file()
            assert relative_path in skill_text


class TestWfrunnerPlannerSkill:
    def test_wfrunner_planner_has_references_and_renumber_script(self) -> None:
        _assert_exact_reference_docs("wfrunner-planner")

        scripts_dir = _skill_path("wfrunner-planner") / "scripts"
        assert scripts_dir.is_dir(), f"Expected directory to exist: {scripts_dir.relative_to(ROOT)}"
        assert sorted(path.name for path in scripts_dir.iterdir() if path.is_file()) == [
            "renumber_steps.py"
        ]

    def test_wfrunner_planner_references_plan_sources_of_truth(self) -> None:
        skill_text = _all_markdown_text("wfrunner-planner")

        for relative_path in (
            "schemas/implementation-step.schema.json",
            "tools/plan_parser.py",
            "tools/plan_validator.py",
        ):
            assert (ROOT / relative_path).is_file()
            assert relative_path in skill_text

    def test_wfrunner_planner_renumber_script_imports_safely(self) -> None:
        script_path = _renumber_script_path()
        assert script_path.is_file(), f"Expected file to exist: {script_path.relative_to(ROOT)}"

        spec = importlib.util.spec_from_file_location("renumber_steps_test_module", script_path)
        assert spec is not None
        assert spec.loader is not None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert isinstance(module, ModuleType)
        assert callable(getattr(module, "main", None))

    def test_wfrunner_planner_renumber_script_dry_run_default_and_write_mode(
        self,
        tmp_path: Path,
    ) -> None:
        script_path = _renumber_script_path()
        assert script_path.is_file(), f"Expected file to exist: {script_path.relative_to(ROOT)}"

        plan_path = tmp_path / "plan.md"
        original_plan = textwrap.dedent("""\
            # Plan

            ### STEP-001 - First

            ```yaml
            schema_version: 1
            id: STEP-001
            title: First
            type: HUMAN_GATE
            ```

            ### STEP-001.001 - Inserted

            ```yaml
            schema_version: 1
            id: STEP-001.001
            title: Inserted
            type: HUMAN_GATE
            ```

            ### STEP-003 - Third

            ```yaml
            schema_version: 1
            id: STEP-003
            title: Third
            type: HUMAN_GATE
            ```
            """)
        plan_path.write_text(original_plan, encoding="utf-8")

        dry_run = subprocess.run(
            [sys.executable, str(script_path), "--plan", str(plan_path)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        assert dry_run.returncode == 0, dry_run.stderr
        assert plan_path.read_text(encoding="utf-8") == original_plan

        write_run = subprocess.run(
            [sys.executable, str(script_path), "--plan", str(plan_path), "--write"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        assert write_run.returncode == 0, write_run.stderr
        updated_plan = plan_path.read_text(encoding="utf-8")
        assert "### STEP-001.001 - Inserted" not in updated_plan
        assert "id: STEP-001.001" not in updated_plan
        assert "### STEP-002 - Inserted" in updated_plan
        assert "id: STEP-002" in updated_plan
        assert "### STEP-003 - Third" in updated_plan
        assert "id: STEP-003" in updated_plan


class TestWfrunnerDocsSkill:
    def test_wfrunner_docs_has_exactly_requested_reference_docs(self) -> None:
        _assert_exact_reference_docs("wfrunner-docs")

    def test_wfrunner_docs_hierarchy_lists_specs_in_requested_order(self) -> None:
        hierarchy_text = _read_text(_references_path("wfrunner-docs") / "doc-hierarchy.md")

        previous_index = -1
        for doc_name in EXPECTED_DOCS_HIERARCHY:
            relative_path = f"docs/specs/{doc_name}"
            assert (ROOT / "docs" / "specs" / doc_name).is_file()
            current_index = hierarchy_text.index(relative_path)
            assert current_index > previous_index
            previous_index = current_index


def test_project_skills_are_excluded_from_python_packaging() -> None:
    with (ROOT / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)

    package_find = pyproject["tool"]["setuptools"]["packages"]["find"]
    assert package_find["include"] == ["tools*"]


def test_only_planner_skill_templates_are_included_in_pyinstaller_datas() -> None:
    spec_tree = ast.parse(_read_text(ROOT / "wfrunner.spec"))
    datas_assignment = next(
        node
        for node in spec_tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_datas" for target in node.targets)
    )

    data_strings = [
        node.value
        for node in ast.walk(datas_assignment.value)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]

    assert any(".github/skills/wfrunner-planner" in value for value in data_strings)
    assert not any(".github/skills/specbuilder" in value for value in data_strings)


def test_specbuilder_is_not_registered_as_active_project_skill() -> None:
    active_skill_names = {
        path.name
        for path in SKILLS_ROOT.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    }

    assert "specbuilder" not in active_skill_names
