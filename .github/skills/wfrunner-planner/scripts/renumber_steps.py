"""Renumber WaterfallRunner plan step IDs contiguously."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.plan_parser import ParsedStep, parse_plan
from tools.plan_validator import validate_plan


_STEP_HEADING_RE = re.compile(
    "^(###\\s+)(STEP-\\d{3}(?:\\.\\d{3})?)(\\s*[\\u2014\\u2013-]\\s*.+?)$"
)
_YAML_ID_RE = re.compile(
    r"^(\s*id:\s*)(['\"]?)(STEP-\d{3}(?:\.\d{3})?)(\2)(\s*(?:#.*)?)$"
)


class RenumberChange:
    """A single step ID renumbering."""

    __slots__ = ("line_number", "new_id", "old_id")

    def __init__(self, line_number: int, old_id: str, new_id: str) -> None:
        self.line_number = line_number
        self.old_id = old_id
        self.new_id = new_id


class RenumberError(Exception):
    """Raised when a plan cannot be safely renumbered."""


def renumber_plan_text(text: str) -> tuple[str, list[RenumberChange]]:
    """Return plan text with contiguous major STEP IDs."""

    parse_result = parse_plan(text)
    if parse_result.errors:
        details = "; ".join(
            f"line {error.line_number}: {error.message}" for error in parse_result.errors
        )
        raise RenumberError(f"Cannot renumber plan with parse errors: {details}")

    if not parse_result.steps:
        raise RenumberError("Cannot renumber a plan with no steps.")

    newline = "\r\n" if "\r\n" in text else "\n"
    has_trailing_newline = text.endswith(("\n", "\r\n"))
    lines = text.splitlines()
    changes: list[RenumberChange] = []

    for index, step in enumerate(parse_result.steps, start=1):
        new_id = f"STEP-{index:03d}"
        _replace_heading_id(lines, step, new_id)
        old_yaml_id = str(step.yaml_block.get("id", step.heading_id))
        _replace_yaml_id(lines, step, new_id)

        if step.heading_id != new_id or old_yaml_id != new_id:
            changes.append(
                RenumberChange(
                    line_number=step.heading_line_number,
                    old_id=step.heading_id,
                    new_id=new_id,
                )
            )

    renumbered = newline.join(lines)
    if has_trailing_newline:
        renumbered += newline

    validation_errors = _validation_errors(renumbered)
    if validation_errors:
        raise RenumberError(
            "Renumbered plan failed validation:\n" + "\n".join(validation_errors)
        )

    return renumbered, changes


def _replace_heading_id(lines: list[str], step: ParsedStep, new_id: str) -> None:
    heading_index = step.heading_line_number - 1
    match = _STEP_HEADING_RE.match(lines[heading_index])
    if match is None:
        raise RenumberError(
            f"Cannot rewrite heading at line {step.heading_line_number}: "
            f"{lines[heading_index]}"
        )

    lines[heading_index] = f"{match.group(1)}{new_id}{match.group(3)}"


def _replace_yaml_id(lines: list[str], step: ParsedStep, new_id: str) -> None:
    yaml_start_index = step.yaml_line_number - 1
    yaml_end_index = yaml_start_index + len(step.yaml_raw.splitlines())

    for line_index in range(yaml_start_index, yaml_end_index):
        match = _YAML_ID_RE.match(lines[line_index])
        if match is None:
            continue

        lines[line_index] = (
            f"{match.group(1)}{match.group(2)}{new_id}"
            f"{match.group(4)}{match.group(5)}"
        )
        return

    raise RenumberError(
        f"Cannot find YAML id for {step.heading_id} near line {step.yaml_line_number}."
    )


def _validation_errors(text: str) -> list[str]:
    parse_result = parse_plan(text)
    validation_result = validate_plan(
        parse_result,
        schemas_dir=PROJECT_ROOT / "schemas",
    )
    return [
        f"{error.step_id or 'plan'}: {error.message}"
        for error in validation_result.errors
    ]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Renumber WaterfallRunner plan headings and YAML id fields."
    )
    parser.add_argument(
        "--plan",
        required=True,
        type=Path,
        help="Path to the WaterfallRunner plan Markdown file.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the renumbered plan. Defaults to dry-run validation only.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the renumbering command."""

    args = _build_parser().parse_args(argv)
    plan_path = args.plan

    if not plan_path.is_file():
        print(f"Plan file not found: {plan_path}", file=sys.stderr)
        return 2

    try:
        original_text = plan_path.read_text(encoding="utf-8")
        renumbered_text, changes = renumber_plan_text(original_text)
    except OSError as exc:
        print(f"Failed to read plan {plan_path}: {exc}", file=sys.stderr)
        return 2
    except RenumberError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.write:
        if renumbered_text != original_text:
            try:
                plan_path.write_text(renumbered_text, encoding="utf-8")
            except OSError as exc:
                print(f"Failed to write plan {plan_path}: {exc}", file=sys.stderr)
                return 2
        print(f"Renumbered {len(changes)} step(s) in {plan_path}.")
        return 0

    if changes:
        print("Dry run: renumbering would make these changes:")
        for change in changes:
            print(f"  line {change.line_number}: {change.old_id} -> {change.new_id}")
    else:
        print("Dry run: plan step IDs are already contiguous.")
    print("Validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
