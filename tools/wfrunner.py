"""Unified CLI entry point for WaterfallRunner.

Usage:
    wfrunner <subcommand> [options]

Subcommands:
    run         Execute implementation steps from a plan.
    validate    Validate an implementation plan.
    status      Show execution status.
    init        Scaffold a .wfrunner/ project directory.
"""

from __future__ import annotations

import argparse
from importlib import metadata as importlib_metadata
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

from tools import review_base
from tools.config import BUILTIN_PROTECTED_PATHS, ConfigNotFoundError, load_config
from tools.constants import PROGRESS_FIELD_STATE, PROGRESS_FIELD_STEPS
from tools.data_path import MissingRuntimeResourceError
from tools.init_project import init as init_project_init
from tools.plan_compiler import CompiledPlanError, compile_plan_data
from tools.plan_parser import parse_plan_file


PACKAGING_ERROR_EXIT_CODE = 2


def _get_version() -> str:
    try:
        return importlib_metadata.version("wfrunner")
    except importlib_metadata.PackageNotFoundError:
        pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        if not pyproject_path.exists():
            return "unknown"
        with pyproject_path.open("rb") as pyproject_file:
            project = tomllib.load(pyproject_file).get("project", {})
        version = project.get("version")
        if isinstance(version, str):
            return version
        return "unknown"


__version__ = _get_version()


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="wfrunner",
        description="WaterfallRunner — specs-driven orchestration for AI-assisted implementation.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="subcommand")

    # --- run ---
    run_parser = subparsers.add_parser("run", help="Execute implementation steps from a plan.")
    run_parser.add_argument("plan_path", help="Path to the implementation plan.")
    run_parser.add_argument("--config", default=None, help="Path to wfrunner.toml config file.")
    run_parser.add_argument("--prepare-only", action="store_true", default=False,
                            help="Scaffold automation files without executing.")
    run_parser.add_argument("--next-step-only", action="store_true", default=False,
                            help="Execute exactly one step and stop.")
    run_parser.add_argument("--resume", action="store_true", default=False,
                            help="Resume from the last run.")
    run_parser.add_argument("--reset", action="store_true", default=False,
                            help="Reset execution and rebase git branch.")
    run_parser.add_argument("--reset-current-step", action="store_true", default=False,
                            help="Reset current step to TODO.")
    run_parser.add_argument("--approve-human-gates", action="store_true", default=False,
                            help="Auto-approve HUMAN_GATE steps after successful pre-analysis.")
    run_parser.add_argument(
        "--no-scope-enforcement",
        action="store_true",
        default=False,
        help="Continue without Git-backed change detection and scope enforcement.",
    )

    # --- validate ---
    validate_parser = subparsers.add_parser("validate", help="Validate an implementation plan.")
    validate_parser.add_argument("plan_path", help="Path to the implementation plan.")
    validate_parser.add_argument("--config", default=None, help="Path to wfrunner.toml config file.")

    # --- status ---
    status_parser = subparsers.add_parser("status", help="Show execution status.")
    status_parser.add_argument("plan_path", help="Path to the implementation plan.")
    status_parser.add_argument("--config", default=None, help="Path to wfrunner.toml config file.")

    # --- init ---
    subparsers.add_parser("init", help="Scaffold a .wfrunner/ project directory.")

    # --- review-base ---
    review_base_parser = subparsers.add_parser(
        "review-base",
        help="Record a plan baseline SHA and emit a scoped review diff.",
    )
    review_base_sub = review_base_parser.add_subparsers(dest="review_base_command")
    rb_record = review_base_sub.add_parser(
        "record", help="Record the plan baseline HEAD SHA (create-if-absent)."
    )
    rb_record.add_argument("--file", required=True, help="Path to the baseline SHA file.")
    rb_diff = review_base_sub.add_parser(
        "diff", help="Write a unified patch of base..HEAD."
    )
    rb_diff.add_argument("--base-file", required=True, help="Path to the baseline SHA file.")
    rb_diff.add_argument("--out", required=True, help="Path to write the unified patch.")

    return parser


def _load_run_config(args: argparse.Namespace) -> Any:
    """Load config for the run subcommand, raising ConfigNotFoundError if missing."""
    if args.config:
        return load_config(config_file=Path(args.config))

    # Try default location
    return load_config(project_root=Path.cwd())


def _handle_run(args: argparse.Namespace) -> int:
    """Execute the run subcommand."""
    from tools.run_plan import prepare_run, reset_run, reset_current_step, run

    try:
        config = _load_run_config(args)
    except ConfigNotFoundError as exc:
        print(
            f"Error: {exc}\nRun 'wfrunner init' to create configuration.",
            file=sys.stderr,
        )
        return 1

    if args.reset:
        return reset_run(config)

    if args.reset_current_step:
        return reset_current_step(config)

    if args.prepare_only:
        if args.approve_human_gates:
            print(
                "Warning: --approve-human-gates has no effect with --prepare-only.",
                file=sys.stderr,
            )
        ctx = prepare_run(str(args.plan_path), config, resume=args.resume)
        if ctx.get("error"):
            print(f"Error: {ctx['error']}", file=sys.stderr)
            return 1
        print("Preparation complete.")
        return 0

    # Default: whole-plan mode
    ctx = prepare_run(str(args.plan_path), config, resume=args.resume)
    if ctx.get("error"):
        print(f"Error: {ctx['error']}", file=sys.stderr)
        return 1

    run_kwargs = {
        "one_step": args.next_step_only,
        "approve_human_gates": args.approve_human_gates,
    }
    if args.no_scope_enforcement:
        run_kwargs["no_scope_enforcement"] = True
    return run(ctx, **run_kwargs)


def _handle_validate(args: argparse.Namespace) -> int:
    """Validate an implementation plan."""
    plan_path = Path(args.plan_path)
    if not plan_path.exists():
        print(f"Error: Plan file not found: {plan_path}", file=sys.stderr)
        return 2

    # Try to load config for protected_paths validation
    protected_paths = BUILTIN_PROTECTED_PATHS
    if args.config:
        try:
            config = load_config(config_file=Path(args.config))
            protected_paths = config.protected_paths
        except ConfigNotFoundError:
            print(
                "Note: Project-specific protected paths were unavailable; "
                "using built-in protected paths.",
                file=sys.stderr,
            )
    else:
        try:
            config = load_config(project_root=Path.cwd())
            protected_paths = config.protected_paths
        except ConfigNotFoundError:
            print(
                "Note: Project-specific protected paths were unavailable; "
                "using built-in protected paths.",
                file=sys.stderr,
            )

    try:
        compiled = compile_plan_data(plan_path, protected_paths=protected_paths)
    except CompiledPlanError as exc:
        print(f"Validation failed: {exc}")
        return 1

    print(f"Plan is valid. {len(compiled['steps'])} step(s) found.")
    return 0


def _handle_status(args: argparse.Namespace) -> int:
    """Show execution status for a plan."""
    plan_path = Path(args.plan_path)
    if not plan_path.exists():
        print(f"Error: Plan file not found: {plan_path}", file=sys.stderr)
        return 2

    parse_result = parse_plan_file(plan_path)
    if not parse_result.ok:
        print(f"Error: Could not parse plan: {plan_path}", file=sys.stderr)
        return 1

    automation_dir = Path(".wfrunner") / "automation"
    try:
        config = _load_run_config(args)
        automation_dir = Path(config.automation_dir)
    except ConfigNotFoundError as exc:
        if args.config:
            print(
                f"Error: {exc}\nRun 'wfrunner init' to create configuration.",
                file=sys.stderr,
            )
            return 1

    # Look for progress.json
    progress_path = automation_dir / "progress.json"

    if not progress_path.exists():
        print("No execution data found.")
        return 0

    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    steps_progress = progress.get(PROGRESS_FIELD_STEPS, {})

    # Print status table
    print(f"{'Step ID':<15} {'Title':<40} {'State':<15}")
    print("-" * 70)
    for step in parse_result.steps:
        step_id = step.heading_id
        title = step.heading_title[:40]
        step_state = steps_progress.get(step_id, {}).get(PROGRESS_FIELD_STATE, "UNKNOWN")
        print(f"{step_id:<15} {title:<40} {step_state:<15}")

    return 0


def _handle_init(_args: argparse.Namespace) -> int:
    return init_project_init()


def _handle_review_base(args: argparse.Namespace) -> int:
    """Record a plan baseline SHA or emit a scoped review diff."""
    if args.review_base_command == "record":
        return review_base.record(Path(args.file))
    if args.review_base_command == "diff":
        return review_base.diff(Path(args.base_file), Path(args.out))
    print(
        "Error: review-base requires a subcommand: 'record' or 'diff'.",
        file=sys.stderr,
    )
    return 2


_HANDLERS = {
    "run": _handle_run,
    "validate": _handle_validate,
    "status": _handle_status,
    "init": _handle_init,
    "review-base": _handle_review_base,
}


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the appropriate handler.

    Args:
        argv: Command-line arguments. Defaults to sys.argv[1:].

    Returns:
        Exit code (0 for success).
    """
    parser = build_parser()

    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        parser.print_help(sys.stderr)
        return 2

    args = parser.parse_args(argv)

    handler = _HANDLERS.get(args.subcommand)
    if handler is None:
        parser.print_help(sys.stderr)
        return 2

    try:
        return handler(args)
    except MissingRuntimeResourceError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return PACKAGING_ERROR_EXIT_CODE


if __name__ == "__main__":
    sys.exit(main())
