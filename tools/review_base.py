"""Scope helper for WaterfallRunner codereview steps.

A ``codereview`` (ANALYSIS) step should review a plan's *own* changes, not the
whole repository. Because branch layout varies and pre-analysis shell one-liners
are not portable across Windows and Linux, this helper provides the two small,
cross-platform operations a plan needs, invoked from a step's ``pre_analysis``:

    python -m tools.review_base record --file <sha-file>
    python -m tools.review_base diff --base-file <sha-file> --out <patch-file>

``record`` writes the current ``HEAD`` SHA to ``<sha-file>`` exactly once
(create-if-absent), so re-running or resuming a plan never moves the baseline.
Run it from the first step of the plan.

``diff`` emits a unified patch of ``<base>..HEAD`` to ``<out>`` for the reviewer
to read. Run it from the ``codereview`` step's ``pre_analysis``.

Both operations degrade gracefully: when git is unavailable or no baseline was
recorded, they exit 0 and write a clearly marked fallback note so the reviewer
can fall back to reviewing the plan's declared ``allowed_files``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_GIT_TIMEOUT_SECONDS = 30

# Sentinel first line written to the patch artifact when no diff can be produced.
NO_DIFF_MARKER = "# codereview: no diff available"


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run a git command in the current working tree.

    Returns the completed process, or None when git is unavailable or times out.
    """
    try:
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _head_sha() -> str | None:
    """Return the current HEAD SHA, or None when git is unavailable."""
    result = _run_git(["rev-parse", "HEAD"])
    if result is None or result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def _write_no_diff(out_path: Path, reason: str) -> None:
    """Write the fallback marker so the reviewer knows to use allowed_files."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        f"{NO_DIFF_MARKER}\n"
        f"# reason: {reason}\n"
        "# Review scope falls back to the plan's declared allowed_files.\n",
        encoding="utf-8",
    )


def record(sha_file: Path) -> int:
    """Record the plan baseline HEAD SHA once (create-if-absent).

    Returns 0 always; a missing git binary is non-fatal so the plan proceeds.
    """
    if sha_file.exists() and sha_file.read_text(encoding="utf-8").strip():
        print(f"Baseline already recorded: {sha_file}")
        return 0

    sha = _head_sha()
    if sha is None:
        print("git unavailable; baseline not recorded (review will fall back to allowed_files).")
        return 0

    sha_file.parent.mkdir(parents=True, exist_ok=True)
    sha_file.write_text(f"{sha}\n", encoding="utf-8")
    print(f"Recorded review baseline {sha} to {sha_file}")
    return 0


def diff(base_file: Path, out_path: Path) -> int:
    """Write a unified patch of base..HEAD to out_path.

    Returns 0 always; when git is unavailable or no baseline exists, writes the
    NO_DIFF_MARKER fallback instead of failing.
    """
    if not base_file.exists() or not base_file.read_text(encoding="utf-8").strip():
        _write_no_diff(out_path, "baseline not recorded")
        print(f"No baseline at {base_file}; wrote fallback marker to {out_path}")
        return 0

    base = base_file.read_text(encoding="utf-8").strip()
    head = _head_sha()
    if head is None:
        _write_no_diff(out_path, "git unavailable")
        print(f"git unavailable; wrote fallback marker to {out_path}")
        return 0

    result = _run_git(["diff", f"{base}..HEAD"])
    if result is None or result.returncode != 0:
        _write_no_diff(out_path, f"git diff failed for base {base}")
        print(f"git diff failed for base {base}; wrote fallback marker to {out_path}")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# codereview base diff\n"
        f"# base: {base}\n"
        f"# head: {head}\n"
        f"# generated: {datetime.now(timezone.utc).isoformat()}\n"
        "#\n"
    )
    out_path.write_text(header + result.stdout, encoding="utf-8")
    print(f"Wrote diff {base}..{head} to {out_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the review_base argument parser."""
    parser = argparse.ArgumentParser(
        prog="review_base",
        description="Record a plan baseline SHA and emit a scoped review diff.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    record_parser = subparsers.add_parser("record", help="Record the plan baseline HEAD SHA (create-if-absent).")
    record_parser.add_argument("--file", required=True, help="Path to the baseline SHA file.")

    diff_parser = subparsers.add_parser("diff", help="Write a unified patch of base..HEAD.")
    diff_parser.add_argument("--base-file", required=True, help="Path to the baseline SHA file.")
    diff_parser.add_argument("--out", required=True, help="Path to write the unified patch.")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the requested operation."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "record":
        return record(Path(args.file))
    if args.command == "diff":
        return diff(Path(args.base_file), Path(args.out))

    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
