"""Tests for tools.review_base — plan baseline recording and scoped diffs."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools import review_base


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _make_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True, check=True)
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)
    return repo


def _commit(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, capture_output=True, check=True)


class TestRecord:
    def test_record_writes_head_sha(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        sha_file = repo / ".wfrunner" / "base.sha"

        assert review_base.record(sha_file) == 0
        assert sha_file.read_text(encoding="utf-8").strip() == _git(repo, "rev-parse", "HEAD")

    def test_record_is_create_if_absent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        sha_file = repo / ".wfrunner" / "base.sha"
        sha_file.parent.mkdir(parents=True)
        sha_file.write_text("ORIGINAL\n", encoding="utf-8")

        assert review_base.record(sha_file) == 0
        assert sha_file.read_text(encoding="utf-8").strip() == "ORIGINAL"

    def test_record_without_git_is_noop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(review_base, "_run_git", lambda args: None)
        sha_file = tmp_path / "base.sha"

        assert review_base.record(sha_file) == 0
        assert not sha_file.exists()


class TestDiff:
    def test_diff_emits_patch_of_plan_changes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        sha_file = repo / ".wfrunner" / "base.sha"
        review_base.record(sha_file)

        (repo / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
        _commit(repo, "step change")

        out = repo / ".wfrunner" / "review.patch"
        assert review_base.diff(sha_file, out) == 0
        content = out.read_text(encoding="utf-8")
        assert "# codereview base diff" in content
        assert "a.txt" in content
        assert "+two" in content

    def test_diff_fallback_when_baseline_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        out = repo / "review.patch"

        assert review_base.diff(repo / "missing.sha", out) == 0
        assert out.read_text(encoding="utf-8").startswith(review_base.NO_DIFF_MARKER)

    def test_diff_fallback_when_git_unavailable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        sha_file = tmp_path / "base.sha"
        sha_file.write_text("deadbeef\n", encoding="utf-8")
        monkeypatch.setattr(review_base, "_run_git", lambda args: None)
        out = tmp_path / "review.patch"

        assert review_base.diff(sha_file, out) == 0
        assert review_base.NO_DIFF_MARKER in out.read_text(encoding="utf-8")


class TestCli:
    def test_cli_record_then_diff(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)

        assert review_base.main(["record", "--file", ".wfrunner/base.sha"]) == 0
        assert (repo / ".wfrunner" / "base.sha").exists()

        (repo / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
        _commit(repo, "step change")

        assert review_base.main(
            ["diff", "--base-file", ".wfrunner/base.sha", "--out", ".wfrunner/review.patch"]
        ) == 0
        assert (repo / ".wfrunner" / "review.patch").exists()

    def test_cli_requires_subcommand(self) -> None:
        with pytest.raises(SystemExit):
            review_base.main([])
