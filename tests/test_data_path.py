"""Tests for tools.data_path module."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.data_path import (
    MissingRuntimeResourceError,
    get_project_root,
    get_work_project_root,
    require_runtime_resource,
)


class TestGetProjectRoot:
    """Tests for get_project_root()."""

    def test_returns_project_root_in_development_mode(self) -> None:
        root = get_project_root()
        assert isinstance(root, Path)
        assert (root / "schemas" / "implementation-step.schema.json").exists()

    def test_returns_meipass_when_frozen(self) -> None:
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "_MEIPASS", "/tmp/fake_bundle", create=True):
            root = get_project_root()
        assert root == Path("/tmp/fake_bundle")

    def test_schemas_dir_accessible_from_project_root(self) -> None:
        root = get_project_root()
        assert (root / "schemas").is_dir()

    def test_docs_schemas_dir_accessible_from_project_root(self) -> None:
        root = get_project_root()
        assert (root / "docs" / "schemas").is_dir()

    def test_missing_runtime_resource_reports_packaging_diagnostic(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("tools.data_path.get_project_root", lambda: tmp_path)

        with pytest.raises(MissingRuntimeResourceError) as exc_info:
            require_runtime_resource(Path("schemas/config.schema.json"), description="config schema")

        message = str(exc_info.value)
        assert "Missing runtime resource" in message
        assert "schemas/config.schema.json" in message
        assert "config schema" in message
        assert "packaged executable" in message

    def test_main_returns_packaging_exit_code_for_missing_bundled_resource(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from tools import wfrunner

        bundle_root = tmp_path / "incomplete-bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()
        monkeypatch.chdir(project_root)
        monkeypatch.setattr("tools.data_path.get_project_root", lambda: bundle_root)

        exit_code = wfrunner.main(["init"])

        assert exit_code == wfrunner.PACKAGING_ERROR_EXIT_CODE


class TestGetWorkProjectRoot:
    """Tests for get_work_project_root()."""

    def test_work_project_root_finds_git_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("WFRUNNER_ROOT", raising=False)
        root = get_work_project_root()
        assert root == tmp_path

    def test_work_project_root_from_subdirectory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        subdir = tmp_path / "a" / "b" / "c"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)
        monkeypatch.delenv("WFRUNNER_ROOT", raising=False)
        root = get_work_project_root()
        assert root == tmp_path

    def test_work_project_root_respects_root_flag(self) -> None:
        root = get_work_project_root(root_override="/some/path")
        assert root == Path("/some/path")

    def test_work_project_root_respects_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WFRUNNER_ROOT", str(tmp_path))
        root = get_work_project_root()
        assert root == tmp_path

    def test_work_project_root_cli_overrides_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WFRUNNER_ROOT", "/env/path")
        root = get_work_project_root(root_override=str(tmp_path))
        assert root == tmp_path

    def test_work_project_root_fails_outside_git(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("WFRUNNER_ROOT", raising=False)
        with pytest.raises(SystemExit):
            get_work_project_root()

    def test_work_project_root_handles_git_worktree(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Create a fake git worktree: .git is a file, not a directory
        real_repo = tmp_path / "real_repo"
        real_repo.mkdir()
        subprocess.run(["git", "init", str(real_repo)], capture_output=True, check=True)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / ".git").write_text(f"gitdir: {real_repo / '.git'}", encoding="utf-8")
        monkeypatch.chdir(worktree)
        monkeypatch.delenv("WFRUNNER_ROOT", raising=False)
        # git rev-parse --show-toplevel should handle this
        root = get_work_project_root()
        assert isinstance(root, Path)
