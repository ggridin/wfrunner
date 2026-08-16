"""Data path resolution for development and PyInstaller frozen mode."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


class MissingRuntimeResourceError(FileNotFoundError):
    """Raised when a bundled runtime resource is missing."""


def get_project_root() -> Path:
    """Return the project root directory.

    In development mode, returns the repository root (parent of tools/).
    In PyInstaller frozen mode, returns sys._MEIPASS where bundled data
    files are extracted.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def require_runtime_resource(relative_path: str | Path, *, description: str = "runtime resource") -> Path:
    """Return a bundled resource path or raise an actionable packaging error."""
    resource_relative_path = Path(relative_path)
    resource_path = (
        resource_relative_path
        if resource_relative_path.is_absolute()
        else get_project_root() / resource_relative_path
    )
    if resource_path.exists():
        return resource_path

    display_path = resource_relative_path.as_posix()
    raise MissingRuntimeResourceError(
        f"Missing runtime resource ({description}): {display_path}. "
        "The packaged executable may be incomplete or stale; rebuild it with build.py "
        "and verify the PyInstaller data-file contract."
    )


def get_work_project_root(root_override: str | None = None) -> Path:
    """Return the work project's git repo root.

    Resolution order:
    1. root_override parameter (from --root CLI flag)
    2. WFRUNNER_ROOT environment variable
    3. git rev-parse --show-toplevel from CWD
    4. Fail with a clear error if none of the above resolve.
    """
    if root_override is not None:
        return Path(root_override)

    env_root = os.environ.get("WFRUNNER_ROOT")
    if env_root:
        return Path(env_root)

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise SystemExit(
            "Error: Not inside a git repository and no --root or WFRUNNER_ROOT override provided.\n"
            "Run 'wfrunner init' from a git repository, or pass --root <path>."
        ) from exc
