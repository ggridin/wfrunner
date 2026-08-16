"""Tests for the PyInstaller build spec."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest


RUNTIME_RESOURCE_CONTRACTS = (
    Path("schemas/config.schema.json"),
    Path("schemas/implementation-step.schema.json"),
    Path("schemas/compiled-plan.schema.json"),
    Path("schemas/agent-result.schema.json"),
    Path("schemas/command-summary.schema.json"),
    Path("docs/schemas/progress.schema.json"),
    Path("prompts/system_prompt.implementation.md"),
    Path("prompts/system_prompt.analysis.md"),
)


def test_runtime_resource_contracts_exist_as_source_files() -> None:
    for resource_path in RUNTIME_RESOURCE_CONTRACTS:
        assert resource_path.is_file(), f"Missing runtime resource contract: {resource_path}"


def test_build_declares_canonical_executable_path() -> None:
    import build

    assert build.CANONICAL_EXECUTABLE_PATH == Path("dist/wfrunner.exe")


def test_build_success_message_uses_canonical_executable_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import build

    artifact_path = tmp_path / "dist" / "wfrunner.exe"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("exe", encoding="utf-8")

    class CompletedBuild:
        returncode = 0

    monkeypatch.setattr(build, "CANONICAL_EXECUTABLE_PATH", artifact_path)
    monkeypatch.setattr(build.subprocess, "run", lambda _command: CompletedBuild())

    assert build.main() == 0
    captured = capsys.readouterr()
    assert f"Output: {artifact_path.as_posix()}" in captured.out.replace("\\", "/")


def test_release_smoke_command_contract_covers_supported_packaged_workflows() -> None:
    import build

    commands = {command.name: command for command in build.RELEASE_SMOKE_COMMANDS}

    assert set(commands) == {"version", "help", "run-help", "validate", "status", "init", "review-base"}
    assert commands["version"].args == ("--version",)
    assert commands["help"].args == ("--help",)
    assert commands["run-help"].args == ("run", "--help")
    assert commands["validate"].expected_exit_code == 0
    assert commands["status"].expected_exit_code == 0
    assert commands["init"].expected_exit_code == 0
    assert commands["review-base"].args == ("review-base", "--help")
    assert commands["review-base"].expected_exit_code == 0


def test_pyinstaller_spec_bundles_wfrunner_metadata() -> None:
    spec_text = Path("wfrunner.spec").read_text(encoding="utf-8")

    assert "copy_metadata" in spec_text
    assert 'copy_metadata("wfrunner")' in spec_text


def test_pyinstaller_spec_extracts_to_system_temp_not_cwd() -> None:
    # Regression (Finding 3 / FINDING-010): extracting the onefile bundle into
    # the current directory unpacks a transient _MEIxxxxxx/ dir into the target
    # repo, polluting its Git worktree and breaking clean-tree detection.
    # Extraction must use the system temp dir (PyInstaller default).
    spec_text = Path("wfrunner.spec").read_text(encoding="utf-8")

    assert 'runtime_tmpdir="."' not in spec_text
    assert "runtime_tmpdir=None" in spec_text.replace(" ", "")


def test_pyinstaller_spec_bundles_runtime_schema_contracts() -> None:
    spec_text = Path("wfrunner.spec").read_text(encoding="utf-8")

    assert '("schemas/*.json", "schemas")' in spec_text
    assert '("docs/schemas/*.json", "docs/schemas")' in spec_text
    assert '("prompts/system_prompt.implementation.md", "prompts")' in spec_text
    assert '("prompts/system_prompt.analysis.md", "prompts")' in spec_text


def test_pyinstaller_spec_bundles_planner_skill_templates_not_specbuilder() -> None:
    spec_text = Path("wfrunner.spec").read_text(encoding="utf-8")

    assert ".github/skills/wfrunner-planner" in spec_text
    assert ".github/skills/specbuilder" not in spec_text


def test_pyproject_declares_runtime_schema_contracts_for_packaged_install() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    data_files = pyproject.get("tool", {}).get("setuptools", {}).get("data-files", {})

    assert "schemas" in data_files
    assert "schemas/*.json" in data_files["schemas"]
    assert "docs/schemas" in data_files
    assert "docs/schemas/*.json" in data_files["docs/schemas"]
    assert "prompts" in data_files
    assert "prompts/system_prompt.implementation.md" in data_files["prompts"]
    assert "prompts/system_prompt.analysis.md" in data_files["prompts"]


def test_pyproject_declares_planner_skill_templates_not_specbuilder_for_packaged_install() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    data_files = pyproject.get("tool", {}).get("setuptools", {}).get("data-files", {})

    serialized = repr(data_files)
    assert ".github/skills/wfrunner-planner" in serialized
    assert ".github/skills/specbuilder" not in serialized