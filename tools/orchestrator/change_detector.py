"""Change detection abstractions for post-agent scope enforcement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
import subprocess


class ChangeDetector(ABC):
    """Detect repository changes made during an agent step."""

    @abstractmethod
    def snapshot_before(self) -> None:
        """Capture baseline state before agent invocation."""

    @abstractmethod
    def detect_changes(self) -> dict[str, str]:
        """Return repository-relative paths mapped to change type."""


class GitChangeDetector(ChangeDetector):
    """Git-backed change detector using ``git status --porcelain``."""

    def __init__(
        self,
        working_dir: Path,
        timeout_seconds: int | None = None,
    ) -> None:
        self.working_dir = Path(working_dir)
        self._timeout_seconds = timeout_seconds
        self._baseline: dict[str, str] | None = None

    def snapshot_before(self) -> None:
        """Capture the pre-agent baseline so pre-existing changes are excluded.

        Implementation steps run on a clean tree, so the baseline is empty and
        the delta equals the raw status. ANALYSIS steps may run on a dirty tree,
        where a raw status would wrongly attribute pre-existing changes to the
        analysis agent, and would let an agent hide its own work by reverting an
        unrelated pre-existing change.
        """
        self._baseline = self._current_changes()

    def detect_changes(self) -> dict[str, str]:
        current = self._current_changes()
        if self._baseline is None:
            return current

        changes = {
            path: change_type
            for path, change_type in current.items()
            if self._baseline.get(path) != change_type
        }
        # A path that was changed before the agent ran but is no longer changed
        # means the agent reverted it, which is itself a modification.
        for path, change_type in self._baseline.items():
            if path not in current:
                changes[path] = change_type
        return changes

    def _current_changes(self) -> dict[str, str]:
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

    @staticmethod
    def _change_type(status: str) -> str | None:
        if status == "??" or "A" in status:
            return "created"
        if "D" in status:
            return "deleted"
        if "M" in status:
            return "modified"
        return None


class FakeChangeDetector(ChangeDetector):
    """Deterministic test change detector."""

    def __init__(self, changes: dict[str, str]) -> None:
        self.changes = dict(changes)

    def snapshot_before(self) -> None:
        return None

    def detect_changes(self) -> dict[str, str]:
        return dict(self.changes)
