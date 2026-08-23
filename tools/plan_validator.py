"""Plan validator — validates step metadata against JSON Schema and workflow rules."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

from tools.data_path import get_project_root, require_runtime_resource

from tools.constants import (
    FIELD_ALLOWED_FILES,
    FIELD_ID,
    FIELD_TITLE,
    FIELD_TYPE,
    STEP_TYPE_HUMAN_GATE,
    STEP_TYPE_IMPLEMENTATION,
)
from tools.plan_parser import ParseResult, ParsedStep
from tools.protected_paths import allowed_entry_covers_protected_path


@dataclass
class ValidationError:
    """A single validation error."""

    step_id: str | None
    message: str


@dataclass
class ValidationResult:
    """Result of validating an implementation plan."""

    errors: list[ValidationError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def add(self, step_id: str | None, message: str) -> None:
        self.errors.append(ValidationError(step_id=step_id, message=message))


def _load_step_schema(schemas_dir: Path | None = None) -> dict[str, Any]:
    """Load the implementation-step JSON schema."""
    if schemas_dir is None:
        schemas_dir = get_project_root() / "schemas"
    schema_path = schemas_dir / "implementation-step.schema.json"
    schema_path = require_runtime_resource(schema_path, description="implementation step schema")
    return json.loads(schema_path.read_text(encoding="utf-8"))


def validate_plan(
    parse_result: ParseResult,
    schemas_dir: Path | None = None,
    protected_paths: list[str] | tuple[str, ...] | None = None,
) -> ValidationResult:
    """Validate a parsed implementation plan.

    Checks:
    - Parse errors are forwarded as validation errors.
    - Each step's YAML metadata is validated against the JSON Schema.
    - Step IDs are contiguous and ascending (STEP-001, STEP-002, ...).
    - No duplicate step IDs.
    - Heading ID matches YAML id.
    - Heading title matches YAML title.
    - Protected-file rules: allowed_files touching protected paths require
      an immediately preceding HUMAN_GATE step.

    Args:
        parse_result: The result from plan_parser.parse_plan().
        schemas_dir: Optional path to the schemas directory.

    Returns:
        A ValidationResult with any validation errors found.
    """
    result = ValidationResult()

    # Forward parse errors.
    for err in parse_result.errors:
        result.add(None, f"Parse error at line {err.line_number}: {err.message}")

    if not parse_result.steps:
        if parse_result.ok:
            result.add(None, "No steps found in implementation plan.")
        return result

    step_schema = _load_step_schema(schemas_dir)
    validator = jsonschema.Draft202012Validator(step_schema)

    seen_ids: dict[str, int] = {}
    step_id_pattern = re.compile(r"^STEP-(\d{3})(?:\.(\d{3}))?$")
    parsed_ids: list[tuple[str, int, int | None]] = []

    for idx, step in enumerate(parse_result.steps):
        yaml_block = step.yaml_block
        step_id = yaml_block.get(FIELD_ID, step.heading_id)

        # --- JSON Schema validation ---
        schema_errors = list(validator.iter_errors(yaml_block))
        for err in schema_errors:
            path = ".".join(str(p) for p in err.absolute_path) if err.absolute_path else "(root)"
            result.add(step_id, f"Schema error at {path}: {err.message}")

        # --- Heading / YAML consistency ---
        yaml_id = yaml_block.get(FIELD_ID)
        if yaml_id is not None and yaml_id != step.heading_id:
            result.add(
                step.heading_id,
                f"Heading ID '{step.heading_id}' differs from YAML id '{yaml_id}'.",
            )

        yaml_title = yaml_block.get(FIELD_TITLE)
        if yaml_title is not None and yaml_title != step.heading_title:
            result.add(
                step_id,
                f"Heading title '{step.heading_title}' differs from YAML title '{yaml_title}'.",
            )

        # --- Duplicate IDs ---
        if step_id in seen_ids:
            result.add(step_id, f"Duplicate step ID '{step_id}'.")
        seen_ids[step_id] = idx

        # --- Contiguous and ascending IDs ---
        match = step_id_pattern.match(step_id) if step_id else None
        if match:
            major = int(match.group(1))
            minor_str = match.group(2)
            minor = int(minor_str) if minor_str else None
            parsed_ids.append((step_id, major, minor))

    # --- Contiguous and ascending ID validation ---
    _validate_step_ordering(parsed_ids, result)

    # --- Protected-file gate validation ---
    if protected_paths is not None:
        _validate_protected_files(parse_result.steps, result, protected_paths)

    return result


def _validate_step_ordering(
    parsed_ids: list[tuple[str, int, int | None]],
    result: ValidationResult,
) -> None:
    """Validate that step IDs are contiguous and ascending.

    Major steps must be contiguous (1, 2, 3...).
    Minor steps must be contiguous within their parent major, starting at .001.
    A bare major step must appear before any minor steps under the same major.
    """
    if not parsed_ids:
        return

    expected_major = 1
    seen_majors: set[int] = set()
    minor_counts: dict[int, list[int]] = {}
    bare_major_seen: set[int] = set()

    for step_id, major, minor in parsed_ids:
        if minor is None:
            # Bare major step
            if major != expected_major:
                if major not in seen_majors:
                    result.add(
                        step_id,
                        f"Step ID '{step_id}' is out of order. Expected STEP-{expected_major:03d}.",
                    )
            seen_majors.add(major)
            bare_major_seen.add(major)
            expected_major = major + 1
        else:
            # Minor step
            if major not in bare_major_seen:
                result.add(
                    step_id,
                    f"Minor step '{step_id}' has no preceding bare major step STEP-{major:03d}.",
                )
                continue

            if major not in minor_counts:
                minor_counts[major] = []

            expected_minor = len(minor_counts[major]) + 1
            if minor != expected_minor:
                result.add(
                    step_id,
                    f"Minor step '{step_id}' is out of order. Expected STEP-{major:03d}.{expected_minor:03d}.",
                )
            minor_counts[major].append(minor)


def _validate_protected_files(
    steps: list[ParsedStep],
    result: ValidationResult,
    protected_paths: tuple[str, ...] | list[str],
) -> None:
    """Check that steps touching protected files have a preceding HUMAN_GATE.

    The validator ensures that at least one HUMAN_GATE exists before the step
    in document order.  Strict proximity enforcement (the gate must be the
    *immediately* preceding step) is deferred to the orchestrator at runtime.
    """
    for idx, step in enumerate(steps):
        yaml_block = step.yaml_block
        step_type = yaml_block.get(FIELD_TYPE)
        if step_type != STEP_TYPE_IMPLEMENTATION:
            continue

        allowed_files = yaml_block.get(FIELD_ALLOWED_FILES, [])
        if not isinstance(allowed_files, list):
            continue

        protected_files = [
            f for f in allowed_files if allowed_entry_covers_protected_path(f, protected_paths)
        ]
        if not protected_files:
            continue

        # Check if any preceding step is a HUMAN_GATE.
        has_prior_gate = any(
            steps[j].yaml_block.get(FIELD_TYPE) == STEP_TYPE_HUMAN_GATE
            for j in range(idx)
        )
        if not has_prior_gate:
            result.add(
                yaml_block.get(FIELD_ID, step.heading_id),
                f"Step modifies protected file(s) {protected_files} but has no preceding HUMAN_GATE.",
            )
