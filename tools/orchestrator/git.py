"""Git helpers for WaterfallRunner orchestration."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tools.config import WaterfallRunnerConfig
from tools.orchestrator.change_detector import GitChangeDetector


def git_timeout(config: WaterfallRunnerConfig | None) -> int:
    return config.git_timeout_seconds if config is not None else 30


def is_worktree_clean(config: WaterfallRunnerConfig | None = None) -> bool:
    """Return True if the Git working tree is clean."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=git_timeout(config),
            check=False,
        )
        return result.returncode == 0 and result.stdout.strip() == ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


class ConfiguredGitChangeDetector(GitChangeDetector):
    """Git change detector that applies the orchestrator Git timeout."""

    def __init__(self, working_dir: Path, timeout_seconds: int) -> None:
        super().__init__(working_dir)
        self._timeout_seconds = timeout_seconds

    def detect_changes(self) -> dict[str, str]:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=self.working_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=self._timeout_seconds,
        )

        changes: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if not line:
                continue

            status = line[:2]
            raw = line[3:]

            if "R" in status and " -> " in raw:
                src, dest = raw.split(" -> ", 1)
                changes[src.replace("\\", "/")] = "deleted"
                changes[dest.replace("\\", "/")] = "renamed"
            else:
                change_type = self._change_type(status)
                if change_type is not None:
                    changes[raw.replace("\\", "/")] = change_type

        return changes


def git_commit(
    step_id: str,
    title: str,
    push: bool = True,
    config: WaterfallRunnerConfig | None = None,
) -> str | None:
    """Stage all changes and create a Git commit. Returns the commit SHA or None."""
    timeout = git_timeout(config)
    push_timeout = config.git_push_timeout_seconds if config is not None else 60
    try:
        subprocess.run(["git", "add", "-A"], capture_output=True, timeout=timeout, check=True)
        result = subprocess.run(
            ["git", "commit", "-m", f"WaterfallRunner: {step_id} — {title}"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode == 0:
            sha_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if push:
                subprocess.run(
                    ["git", "push"],
                    capture_output=True,
                    timeout=push_timeout,
                    check=False,
                )
            return sha_result.stdout.strip() if sha_result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError):
        pass
    return None