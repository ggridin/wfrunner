"""Plan parser — extracts step metadata from Markdown implementation plans."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ParsedStep:
    """A single step extracted from an implementation plan."""

    heading_id: str
    heading_title: str
    heading_line_number: int
    yaml_block: dict[str, Any]
    yaml_raw: str
    yaml_line_number: int


@dataclass
class ParseError:
    """A structural or syntax error found during parsing."""

    line_number: int
    message: str


@dataclass
class ParseResult:
    """Result of parsing an implementation plan."""

    steps: list[ParsedStep] = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


# Regex for step headings: ### STEP-NNN — Title
_STEP_HEADING_RE = re.compile(
    r"^###\s+(STEP-\d{3}(?:\.\d{3})?)\s*[—–-]\s*(.+?)\s*$"
)

# Regex to detect the start of a fenced YAML code block.
_YAML_FENCE_OPEN_RE = re.compile(r"^```ya?ml\s*$", re.IGNORECASE)

# Regex to detect the close of a fenced code block.
_FENCE_CLOSE_RE = re.compile(r"^```\s*$")


def parse_plan(text: str) -> ParseResult:
    """Parse a Markdown implementation plan and extract step metadata.

    Args:
        text: The full Markdown content of the implementation plan.

    Returns:
        A ParseResult with extracted steps and any parse errors.
    """
    lines = text.splitlines()
    result = ParseResult()

    i = 0
    while i < len(lines):
        line = lines[i]
        heading_match = _STEP_HEADING_RE.match(line)
        if heading_match is None:
            i += 1
            continue

        heading_id = heading_match.group(1)
        heading_title = heading_match.group(2).strip()
        heading_line_number = i + 1  # 1-based

        # Look for a YAML fenced block following the heading.
        yaml_block, yaml_raw, yaml_line, parse_end, error = _extract_yaml_block(
            lines, i + 1
        )

        if error is not None:
            result.errors.append(ParseError(line_number=error[0], message=error[1]))
            i = parse_end if parse_end is not None else i + 1
            continue

        if yaml_block is None:
            result.errors.append(
                ParseError(
                    line_number=heading_line_number,
                    message=f"Step {heading_id}: missing YAML metadata block after heading.",
                )
            )
            i += 1
            continue

        step = ParsedStep(
            heading_id=heading_id,
            heading_title=heading_title,
            heading_line_number=heading_line_number,
            yaml_block=yaml_block,
            yaml_raw=yaml_raw,
            yaml_line_number=yaml_line,
        )
        result.steps.append(step)
        i = parse_end if parse_end is not None else i + 1

    return result


def parse_plan_file(path: str | Path) -> ParseResult:
    """Parse an implementation plan from a file path.

    Args:
        path: Path to the Markdown implementation plan file.

    Returns:
        A ParseResult with extracted steps and any parse errors.

    Raises:
        FileNotFoundError: If the plan file does not exist.
    """
    plan_path = Path(path)
    text = plan_path.read_text(encoding="utf-8")
    return parse_plan(text)


def _extract_yaml_block(
    lines: list[str], start: int
) -> tuple[
    dict[str, Any] | None,
    str,
    int,
    int | None,
    tuple[int, str] | None,
]:
    """Extract the first YAML fenced code block starting from *start*.

    Skips blank lines between the heading and the code fence.

    Returns:
        (parsed_dict, raw_yaml, yaml_start_line_1based, end_index, error_tuple)
        - parsed_dict is None when no block is found.
        - error_tuple is (line_number_1based, message) on YAML errors.
    """
    i = start

    # Skip blank lines between heading and fence.
    while i < len(lines) and lines[i].strip() == "":
        i += 1

    # Check for a descriptive paragraph before the YAML block.
    # We allow non-blank, non-fence lines between the heading and the YAML block.
    while i < len(lines):
        if lines[i].strip() == "":
            i += 1
            continue
        if _YAML_FENCE_OPEN_RE.match(lines[i]):
            break
        # If we hit another heading, there's no YAML block for the previous heading.
        if lines[i].startswith("###"):
            return None, "", 0, i, None
        i += 1

    if i >= len(lines):
        return None, "", 0, None, None

    if not _YAML_FENCE_OPEN_RE.match(lines[i]):
        return None, "", 0, i, None

    fence_line = i
    yaml_start = i + 1  # line after opening fence
    yaml_lines: list[str] = []

    i = yaml_start
    while i < len(lines):
        if _FENCE_CLOSE_RE.match(lines[i]):
            break
        yaml_lines.append(lines[i])
        i += 1
    else:
        # Reached end of file without closing fence.
        return (
            None,
            "",
            0,
            None,
            (
                fence_line + 1,
                "Unclosed YAML code fence.",
            ),
        )

    end_index = i + 1  # line after closing fence
    raw_yaml = "\n".join(yaml_lines)
    yaml_line_number = yaml_start + 1  # 1-based

    try:
        parsed = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        detail = str(exc)
        return (
            None,
            raw_yaml,
            yaml_line_number,
            end_index,
            (yaml_line_number, f"Malformed YAML: {detail}"),
        )

    if not isinstance(parsed, dict):
        return (
            None,
            raw_yaml,
            yaml_line_number,
            end_index,
            (yaml_line_number, "YAML block must be a mapping, got a non-mapping value."),
        )

    return parsed, raw_yaml, yaml_line_number, end_index, None
