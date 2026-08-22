"""Progress manager — reads and writes .automation/progress.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from tools.data_path import get_project_root
from tools.constants import (
    PROGRESS_FIELD_AGENT,
    PROGRESS_FIELD_COMMIT,
    PROGRESS_FIELD_COMPLETED_AT,
    PROGRESS_FIELD_FAILURE_REASON,
    PROGRESS_FIELD_FIX_ATTEMPTS,
    PROGRESS_FIELD_MODEL,
    PROGRESS_FIELD_PRE_ANALYSIS,
    PROGRESS_FIELD_STARTED_AT,
    PROGRESS_FIELD_STATE,
    PROGRESS_FIELD_VERIFICATION,
    STATE_TODO,
)


class ProgressValidationError(Exception):
    """Raised when a progress file does not match the progress schema."""

    def __init__(self, path: Path, errors: list[str]) -> None:
        self.path = path
        self.errors = errors
        details = "; ".join(errors)
        super().__init__(f"Invalid progress file {path}: {details}")


class ProgressPlanMismatchError(Exception):
    """Raised when progress does not match the compiled plan checksum."""


def _schema_path() -> Path:
    return get_project_root() / "schemas" / "progress.schema.json"


def _load_schema() -> dict[str, Any]:
    return json.loads(_schema_path().read_text(encoding="utf-8"))


def _format_error_path(error_path: Any) -> str:
    parts = [str(part) for part in error_path]
    return "$" if not parts else "$" + "".join(f".{part}" for part in parts)


def _validate_progress(path: Path, progress: dict[str, Any]) -> None:
    schema = _load_schema()
    validator = Draft202012Validator(schema)
    validation_errors = sorted(validator.iter_errors(progress), key=lambda error: list(error.path))
    if validation_errors:
        errors = [
            f"{_format_error_path(error.path)}: {error.message}"
            for error in validation_errors
        ]
        raise ProgressValidationError(path, errors)


def init_step_progress() -> dict[str, Any]:
    """Create the schema-valid empty progress structure for one step."""
    return {
        PROGRESS_FIELD_STATE: STATE_TODO,
        PROGRESS_FIELD_AGENT: None,
        PROGRESS_FIELD_MODEL: None,
        PROGRESS_FIELD_STARTED_AT: None,
        PROGRESS_FIELD_COMPLETED_AT: None,
        PROGRESS_FIELD_PRE_ANALYSIS: None,
        PROGRESS_FIELD_VERIFICATION: None,
        PROGRESS_FIELD_FIX_ATTEMPTS: 0,
        PROGRESS_FIELD_COMMIT: None,
        PROGRESS_FIELD_FAILURE_REASON: None,
    }


def init_compiled_progress(compiled_plan: dict[str, Any]) -> dict[str, Any]:
    """Create progress metadata keyed to a compiled plan checksum."""
    return {
        "schema_version": 1,
        "source_file": compiled_plan["source_file"],
        "source_sha256": compiled_plan["source_sha256"],
        "steps": {},
    }


def validate_progress_matches_compiled_plan(
    progress: dict[str, Any],
    compiled_plan: dict[str, Any],
) -> None:
    """Ensure progress and compiled plan refer to the same source checksum."""
    if (
        progress.get("source_file") != compiled_plan.get("source_file")
        or progress.get("source_sha256") != compiled_plan.get("source_sha256")
    ):
        raise ProgressPlanMismatchError(
            "Progress does not match the compiled plan; reset or recompile before resuming."
        )


def load_progress(path: Path, validate: bool = True) -> dict[str, Any]:
    """Load progress state from a JSON file.

    Args:
        path: Path to the progress.json file.
        validate: Whether to validate loaded progress against the schema.

    Returns:
        The parsed progress dict.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
        ProgressValidationError: If the file fails schema validation.
    """
    progress = json.loads(path.read_text(encoding="utf-8"))
    if validate:
        _validate_progress(path, progress)
    return progress


def save_progress(path: Path, progress: dict[str, Any]) -> None:
    """Save progress state to a JSON file.

    Args:
        path: Path to the progress.json file.
        progress: The progress dict to persist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(progress, indent=2), encoding="utf-8")
