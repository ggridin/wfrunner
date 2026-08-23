"""Git helpers for WaterfallRunner orchestration."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tools.config import WaterfallRunnerConfig
from tools.orchestrator.change_detector import GitChangeDetector

# Backward-compatible import used by the protected orchestration entry point.
ConfiguredGitChangeDetector = GitChangeDetector


def git_timeout(config: WaterfallRunnerConfig | None) -> int:
    return config.git_timeout_seconds if config is not None else 30


def git_visible_snapshot(
    working_dir: Path,
    timeout_seconds: int = 30,
) -> str | None:
    """Return Git-visible working tree state, or None if it cannot be read."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=working_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    return result.stdout


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