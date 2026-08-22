"""Tests for ChangeDetector implementations.

TDD: These tests define the expected behavior for Phase 2 change
detection before the concrete Git implementation is filled in.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from tools.orchestrator.change_detector import FakeChangeDetector, GitChangeDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command in *repo* and fail loudly on errors."""
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path) -> Path:
    """Initialize a temporary git repository with commit identity configured."""
    _git(repo, "init")
    _git(repo, "config", "user.email", "wfrunner@example.test")
    _git(repo, "config", "user.name", "WaterfallRunner Tests")
    return repo


def _commit_baseline(repo: Path, relative_path: str, content: str = "baseline") -> None:
    """Create and commit a tracked baseline file."""
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", relative_path)
    _git(repo, "commit", "-m", "baseline")


# ===========================================================================
# FakeChangeDetector
# ===========================================================================


class TestFakeChangeDetector:
    """FakeChangeDetector returns deterministic preconfigured changes."""

    def test_returns_preconfigured_changes(self) -> None:
        changes = {
            "tools/orchestrator/change_detector.py": "created",
            "tests/test_change_detector.py": "modified",
        }
        detector = FakeChangeDetector(changes)

        detector.snapshot_before()

        assert detector.detect_changes() == changes


# ===========================================================================
# GitChangeDetector
# ===========================================================================


class TestGitChangeDetector:
    """GitChangeDetector reads git status and reports normalized changes."""

    def test_returns_empty_dict_when_worktree_is_clean(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _commit_baseline(repo, "tracked.txt")
        detector = GitChangeDetector(repo)

        assert detector.detect_changes() == {}

    def test_applies_configured_timeout(self, tmp_path: Path) -> None:
        detector = GitChangeDetector(tmp_path, timeout_seconds=17)

        with patch("tools.orchestrator.change_detector.subprocess.run") as run:
            run.return_value.stdout = ""
            detector.detect_changes()

        run.assert_called_once_with(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
            timeout=17,
        )

    def test_detects_created_files(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        (repo / "created.txt").write_text("new", encoding="utf-8")
        detector = GitChangeDetector(repo)

        assert detector.detect_changes() == {"created.txt": "created"}

    def test_detects_created_files_in_new_directory_individually(
        self, tmp_path: Path
    ) -> None:
        # Regression (Finding 5): ``git status --porcelain`` collapses a new
        # untracked directory to ``pkg/``, which the scope enforcer cannot match
        # against file-level ``allowed_files``. detect_changes must report each
        # created file individually (``--untracked-files=all``).
        repo = _init_repo(tmp_path)
        _commit_baseline(repo, "tracked.txt")
        (repo / "pkg").mkdir()
        (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (repo / "pkg" / "core.py").write_text("x = 1", encoding="utf-8")
        detector = GitChangeDetector(repo)

        assert detector.detect_changes() == {
            "pkg/__init__.py": "created",
            "pkg/core.py": "created",
        }

    def test_detects_modified_files(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _commit_baseline(repo, "tracked.txt")
        (repo / "tracked.txt").write_text("changed", encoding="utf-8")
        detector = GitChangeDetector(repo)

        assert detector.detect_changes() == {"tracked.txt": "modified"}

    def test_detects_deleted_files(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _commit_baseline(repo, "tracked.txt")
        (repo / "tracked.txt").unlink()
        detector = GitChangeDetector(repo)

        assert detector.detect_changes() == {"tracked.txt": "deleted"}

    def test_returns_repository_relative_paths_with_forward_slashes(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _commit_baseline(repo, "nested/dir/tracked.txt")
        (repo / "nested" / "dir" / "tracked.txt").write_text(
            "changed", encoding="utf-8"
        )
        detector = GitChangeDetector(repo)

        assert detector.detect_changes() == {"nested/dir/tracked.txt": "modified"}

    def test_detects_renamed_files_as_deleted_source_and_renamed_dest(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _commit_baseline(repo, "original.txt")
        _git(repo, "mv", "original.txt", "renamed.txt")
        detector = GitChangeDetector(repo)

        assert detector.detect_changes() == {
            "original.txt": "deleted",
            "renamed.txt": "renamed",
        }

    def test_rename_emits_source_as_deleted_and_destination_as_renamed(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _commit_baseline(repo, "src/old_module.py", content="# module code")
        _git(repo, "mv", "src/old_module.py", "src/new_module.py")
        detector = GitChangeDetector(repo)

        changes = detector.detect_changes()

        assert changes["src/old_module.py"] == "deleted"
        assert changes["src/new_module.py"] == "renamed"

    def test_snapshot_before_is_no_op_for_clean_worktree_baseline(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _commit_baseline(repo, "tracked.txt")
        detector = GitChangeDetector(repo)

        assert detector.snapshot_before() is None
        assert detector.detect_changes() == {}
