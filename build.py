"""Convenience build script — invokes PyInstaller with wfrunner.spec."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys


CANONICAL_EXECUTABLE_PATH = Path("dist/wfrunner.exe")


@dataclass(frozen=True)
class ReleaseSmokeCommand:
    name: str
    args: tuple[str, ...]
    expected_exit_code: int


RELEASE_SMOKE_COMMANDS = (
    ReleaseSmokeCommand("version", ("--version",), 0),
    ReleaseSmokeCommand("help", ("--help",), 0),
    ReleaseSmokeCommand("run-help", ("run", "--help"), 0),
    ReleaseSmokeCommand("validate", ("validate", "docs/implementation-plan.md"), 0),
    ReleaseSmokeCommand("status", ("status", "docs/implementation-plan.md"), 0),
    ReleaseSmokeCommand("init", ("init",), 0),
    ReleaseSmokeCommand("review-base", ("review-base", "--help"), 0),
)


def main() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "wfrunner.spec", "--noconfirm", "--clean"],
    )
    if result.returncode == 0:
        if not CANONICAL_EXECUTABLE_PATH.is_file():
            print(
                f"\nBuild failed: expected executable was not created: {CANONICAL_EXECUTABLE_PATH.as_posix()}",
                file=sys.stderr,
            )
            return 1
        print(f"\nBuild succeeded. Output: {CANONICAL_EXECUTABLE_PATH.as_posix()}")
    else:
        print(f"\nBuild failed with exit code {result.returncode}.", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
