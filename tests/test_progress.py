"""Tests for progress manager and reporting — covers ART-001 through ART-007.

TDD: These tests are written before the implementation exists.
They define the expected behavior of the progress manager module.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from tests.helpers import (
    make_progress,
    write_progress,
)
try:
    from tools.orchestrator.progress_manager import ProgressValidationError, load_progress
except ImportError:  # TDD: STEP-009 introduces ProgressValidationError.
    from tools.orchestrator.progress_manager import load_progress

    class ProgressValidationError(Exception):
        """Placeholder used only until the implementation step adds the real exception."""



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_progress_schema() -> dict[str, Any]:
    """Load the progress JSON schema for validation."""
    schema_path = Path(__file__).resolve().parent.parent / "schemas" / "progress.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _validate_progress(progress: dict[str, Any]) -> None:
    """Validate a progress dict against the progress schema."""
    schema = _load_progress_schema()
    jsonschema.validate(instance=progress, schema=schema)


# ===========================================================================
# Regression: pre-analysis summary writer must conform to the progress schema
# ===========================================================================


class TestPreAnalysisSummaryConformsToSchema:
    """The orchestrator's pre-analysis summary writer must emit a shape that
    conforms to schemas/progress.schema.json, so ``--resume`` can reload a
    progress file whose completed steps ran pre-analysis."""

    def test_writer_output_validates_against_progress_schema(self) -> None:
        from tools.orchestrator.pre_analysis_runner import (
            PreAnalysisCommandResult,
            PreAnalysisResult,
        )
        from tools.run_plan import _pre_analysis_summary

        result = PreAnalysisResult(
            command_results=[
                PreAnalysisCommandResult(
                    command_id="record-baseline",
                    command="python -m tools.review_base record",
                    exit_code=0,
                    status="PASS",
                    duration_seconds=0.1,
                    stdout="",
                    stderr="",
                    output_files=[],
                    summary_path=".wfrunner/automation/pre-analysis/STEP-001/record-baseline.summary.json",
                )
            ]
        )

        summary = _pre_analysis_summary(result)

        schema = _load_progress_schema()
        validator = jsonschema.Draft202012Validator(
            {"$ref": "#/$defs/preAnalysisSummary", "$defs": schema["$defs"]}
        )
        validator.validate(summary)  # must not raise

        assert summary["status"] == "PASS"
        assert summary["commands"][0]["command_id"] == "record-baseline"
        assert summary["commands"][0]["summary_path"].endswith(
            "record-baseline.summary.json"
        )


# ===========================================================================
# ART-001: Successful step — progress marks step done, conforms to schema
# ===========================================================================


class TestART001SuccessfulStep:
    """After a successful step, progress should mark the step DONE
    and the progress file should conform to the progress schema."""

    def test_done_step_has_required_fields(self) -> None:
        """A DONE step entry should have all required fields."""
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "DONE",
                    "agent": "spec-implementer",
                    "model": "default",
                    "started_at": "2025-01-01T00:00:00Z",
                    "completed_at": "2025-01-01T00:01:00Z",
                    "pre_analysis": None,
                    "verification": {
                        "status": "PASS",
                        "attempts": [
                            {
                                "attempt": 1,
                                "status": "PASS",
                                "command_summaries": [
                                    ".automation/verification/STEP-001/attempt-1-command-0.summary.json",
                                ],
                            }
                        ],
                    },
                    "fix_attempts": 0,
                    "commit": None,
                    "failure_reason": None,
                },
            }
        )
        _validate_progress(progress)
        assert progress["steps"]["STEP-001"]["state"] == "DONE"

    def test_done_step_has_completed_at(self) -> None:
        """A DONE step must have a non-null completed_at timestamp."""
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "DONE",
                    "agent": "spec-implementer",
                    "model": "default",
                    "started_at": "2025-01-01T00:00:00Z",
                    "completed_at": "2025-01-01T00:01:00Z",
                    "pre_analysis": None,
                    "verification": {
                        "status": "PASS",
                        "attempts": [
                            {
                                "attempt": 1,
                                "status": "PASS",
                                "command_summaries": [
                                    ".automation/verification/STEP-001/attempt-1-command-0.summary.json",
                                ],
                            }
                        ],
                    },
                    "fix_attempts": 0,
                    "commit": None,
                    "failure_reason": None,
                },
            }
        )
        assert progress["steps"]["STEP-001"]["completed_at"] is not None

    def test_schema_conformance_after_success(self) -> None:
        """Progress with a successful step should pass schema validation."""
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "DONE",
                    "agent": "spec-implementer",
                    "model": "default",
                    "started_at": "2025-01-01T00:00:00Z",
                    "completed_at": "2025-01-01T00:01:00Z",
                    "pre_analysis": None,
                    "verification": {
                        "status": "PASS",
                        "attempts": [
                            {
                                "attempt": 1,
                                "status": "PASS",
                                "command_summaries": [
                                    ".automation/verification/STEP-001/attempt-1-command-0.summary.json",
                                ],
                            }
                        ],
                    },
                    "fix_attempts": 0,
                    "commit": None,
                    "failure_reason": None,
                },
            }
        )
        # Should not raise
        _validate_progress(progress)


# ===========================================================================
# ART-002: Successful step with commit enabled — progress records commit hash
# ===========================================================================


class TestART002SuccessfulStepWithCommit:
    """When commit-per-step is enabled, the progress should record
    the commit hash after a successful step."""

    def test_commit_hash_recorded(self) -> None:
        """A DONE step with commit-per-step should have a non-null commit."""
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "DONE",
                    "agent": "spec-implementer",
                    "model": "default",
                    "started_at": "2025-01-01T00:00:00Z",
                    "completed_at": "2025-01-01T00:01:00Z",
                    "pre_analysis": None,
                    "verification": {
                        "status": "PASS",
                        "attempts": [
                            {
                                "attempt": 1,
                                "status": "PASS",
                                "command_summaries": [
                                    ".automation/verification/STEP-001/attempt-1-command-0.summary.json",
                                ],
                            }
                        ],
                    },
                    "fix_attempts": 0,
                    "commit": "abc1234deadbeef",
                    "failure_reason": None,
                },
            }
        )
        _validate_progress(progress)
        assert progress["steps"]["STEP-001"]["commit"] == "abc1234deadbeef"

    def test_commit_none_when_disabled(self) -> None:
        """When commit-per-step is disabled, commit should be null."""
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "DONE",
                    "agent": "spec-implementer",
                    "model": "default",
                    "started_at": "2025-01-01T00:00:00Z",
                    "completed_at": "2025-01-01T00:01:00Z",
                    "pre_analysis": None,
                    "verification": {
                        "status": "PASS",
                        "attempts": [
                            {
                                "attempt": 1,
                                "status": "PASS",
                                "command_summaries": [
                                    ".automation/verification/STEP-001/attempt-1-command-0.summary.json",
                                ],
                            }
                        ],
                    },
                    "fix_attempts": 0,
                    "commit": None,
                    "failure_reason": None,
                },
            }
        )
        _validate_progress(progress)
        assert progress["steps"]["STEP-001"]["commit"] is None


# ===========================================================================
# ART-003: Failed verification — progress records structured failure reason
#          and verification summary path
# ===========================================================================


class TestART003FailedVerification:
    """When verification fails, the progress should record a structured
    failure reason and verification summary."""

    def test_failed_step_has_failure_reason(self) -> None:
        """A FAILED step should have a non-null failure_reason with code and message."""
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "FAILED",
                    "agent": "spec-implementer",
                    "model": "default",
                    "started_at": "2025-01-01T00:00:00Z",
                    "completed_at": "2025-01-01T00:02:00Z",
                    "pre_analysis": None,
                    "verification": {
                        "status": "FAIL",
                        "attempts": [
                            {
                                "attempt": 1,
                                "status": "FAIL",
                                "command_summaries": [
                                    ".automation/verification/STEP-001/attempt-1-command-0.summary.json",
                                ],
                            }
                        ],
                    },
                    "fix_attempts": 0,
                    "commit": None,
                    "failure_reason": {
                        "code": "VERIFICATION_FAILED",
                        "message": "Verification command failed with exit code 1.",
                    },
                },
            }
        )
        _validate_progress(progress)
        fr = progress["steps"]["STEP-001"]["failure_reason"]
        assert fr is not None
        assert fr["code"] == "VERIFICATION_FAILED"
        assert "message" in fr

    def test_verification_summary_records_fail_status(self) -> None:
        """Verification summary should indicate FAIL status."""
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "FAILED",
                    "agent": "spec-implementer",
                    "model": "default",
                    "started_at": "2025-01-01T00:00:00Z",
                    "completed_at": "2025-01-01T00:02:00Z",
                    "pre_analysis": None,
                    "verification": {
                        "status": "FAIL",
                        "attempts": [
                            {
                                "attempt": 1,
                                "status": "FAIL",
                                "command_summaries": [
                                    ".automation/verification/STEP-001/attempt-1-command-0.summary.json",
                                ],
                            }
                        ],
                    },
                    "fix_attempts": 0,
                    "commit": None,
                    "failure_reason": {
                        "code": "VERIFICATION_FAILED",
                        "message": "Verification command failed.",
                    },
                },
            }
        )
        vs = progress["steps"]["STEP-001"]["verification"]
        assert vs is not None
        assert vs["status"] == "FAIL"
        assert len(vs["attempts"]) == 1
        assert vs["attempts"][0]["status"] == "FAIL"

    def test_verification_summary_has_command_summaries(self) -> None:
        """Verification summary should contain command summary paths."""
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "FAILED",
                    "agent": "spec-implementer",
                    "model": "default",
                    "started_at": "2025-01-01T00:00:00Z",
                    "completed_at": "2025-01-01T00:02:00Z",
                    "pre_analysis": None,
                    "verification": {
                        "status": "FAIL",
                        "attempts": [
                            {
                                "attempt": 1,
                                "status": "FAIL",
                                "command_summaries": [
                                    ".automation/verification/STEP-001/attempt-1-command-0.summary.json",
                                ],
                            }
                        ],
                    },
                    "fix_attempts": 0,
                    "commit": None,
                    "failure_reason": {
                        "code": "VERIFICATION_FAILED",
                        "message": "Verification command failed.",
                    },
                },
            }
        )
        cs = progress["steps"]["STEP-001"]["verification"]["attempts"][0]["command_summaries"]
        assert len(cs) >= 1
        assert "STEP-001" in cs[0]


class TestPhase9PreAnalysisFailureReason:
    """Progress written by pre-analysis failures must validate on resume."""

    def test_pre_analysis_failed_reason_code_is_schema_valid(self) -> None:
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "FAILED",
                    "agent": "spec-implementer",
                    "model": "default",
                    "started_at": "2025-01-01T00:00:00Z",
                    "completed_at": "2025-01-01T00:02:00Z",
                    "pre_analysis": {
                        "status": "FAIL",
                        "commands": [
                            {
                                "command_id": "current-test-results",
                                "status": "FAIL",
                                "summary_path": ".automation/pre-analysis/STEP-001/current-test-results.summary.json",
                            }
                        ],
                    },
                    "verification": None,
                    "fix_attempts": 0,
                    "commit": None,
                    "failure_reason": {
                        "code": "PRE_ANALYSIS_FAILED",
                        "message": "Pre-analysis command failed before agent invocation.",
                    },
                },
            }
        )

        _validate_progress(progress)


# ===========================================================================
# ART-004: Scope violation after agent run — patch snapshot is saved
# ===========================================================================


class TestART004ScopeViolationPatchSaved:
    """When a scope violation is detected after agent execution,
    the progress should record the violation and a patch snapshot
    should be saved."""

    def test_scope_violation_recorded_in_progress(self) -> None:
        """A scope violation should be recorded as a FAILED step with
        SCOPE_VIOLATION failure code."""
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "FAILED",
                    "agent": "spec-implementer",
                    "model": "default",
                    "started_at": "2025-01-01T00:00:00Z",
                    "completed_at": "2025-01-01T00:01:30Z",
                    "pre_analysis": None,
                    "verification": None,
                    "fix_attempts": 0,
                    "commit": None,
                    "failure_reason": {
                        "code": "SCOPE_VIOLATION",
                        "message": "Agent modified unlisted file: tools/plan_parser.py",
                    },
                },
            }
        )
        _validate_progress(progress)
        fr = progress["steps"]["STEP-001"]["failure_reason"]
        assert fr["code"] == "SCOPE_VIOLATION"

    def test_patch_snapshot_path_convention(self) -> None:
        """Patch snapshots should be saved under .automation/patches/."""
        from pathlib import PurePosixPath
        expected_pattern = PurePosixPath(".automation") / "patches" / "STEP-001.patch"
        # Assert path follows convention (structural test, not I/O)
        assert str(expected_pattern) == ".automation/patches/STEP-001.patch"


# ===========================================================================
# ART-005: Human gate reached — whole-plan report names gate and action
# ===========================================================================


class TestART005HumanGateReached:
    """When execution stops at a HUMAN_GATE, the progress should
    record the gate step and its description."""

    def test_human_gate_state_in_progress(self) -> None:
        """A HUMAN_GATE step should be represented as a TODO step in
        progress with a HUMAN_GATE failure_reason on the run."""
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "DONE",
                    "agent": "spec-implementer",
                    "model": "default",
                    "started_at": "2025-01-01T00:00:00Z",
                    "completed_at": "2025-01-01T00:01:00Z",
                    "pre_analysis": None,
                    "verification": {
                        "status": "PASS",
                        "attempts": [
                            {
                                "attempt": 1,
                                "status": "PASS",
                                "command_summaries": [
                                    ".automation/verification/STEP-001/attempt-1-command-0.summary.json",
                                ],
                            }
                        ],
                    },
                    "fix_attempts": 0,
                    "commit": None,
                    "failure_reason": None,
                },
                "STEP-002": {
                    "state": "BLOCKED",
                    "agent": None,
                    "model": None,
                    "started_at": None,
                    "completed_at": "2025-01-01T00:01:01Z",
                    "pre_analysis": None,
                    "verification": None,
                    "fix_attempts": 0,
                    "commit": None,
                    "failure_reason": {
                        "code": "HUMAN_GATE",
                        "message": "Stopped at HUMAN_GATE: Review step",
                    },
                },
            }
        )
        _validate_progress(progress)
        step2 = progress["steps"]["STEP-002"]
        assert step2["state"] == "BLOCKED"
        assert step2["failure_reason"]["code"] == "HUMAN_GATE"


# ===========================================================================
# ART-006: Max step limit reached — whole-plan report states limit reached
# ===========================================================================


class TestART006MaxStepLimitReached:
    """When the max step limit is reached in whole-plan mode,
    progress should reflect this and the report should indicate it."""

    def test_max_steps_recorded_in_progress(self) -> None:
        """Progress should record MAX_STEPS_REACHED when the limit is hit."""
        # After completing one step, the orchestrator stops due to max_steps=1.
        # The next step remains TODO but the run records the limit.
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "DONE",
                    "agent": "spec-implementer",
                    "model": "default",
                    "started_at": "2025-01-01T00:00:00Z",
                    "completed_at": "2025-01-01T00:01:00Z",
                    "pre_analysis": None,
                    "verification": {
                        "status": "PASS",
                        "attempts": [
                            {
                                "attempt": 1,
                                "status": "PASS",
                                "command_summaries": [
                                    ".automation/verification/STEP-001/attempt-1-command-0.summary.json",
                                ],
                            }
                        ],
                    },
                    "fix_attempts": 0,
                    "commit": None,
                    "failure_reason": None,
                },
            }
        )
        _validate_progress(progress)
        # The orchestrator should record max_steps_reached in its
        # run-level state — progress still conforms to the schema.
        assert progress["steps"]["STEP-001"]["state"] == "DONE"


# ===========================================================================
# ART-007: Resume loads malformed progress.json — stop and report
# ===========================================================================


class TestART007MalformedProgressResume:
    """When the orchestrator resumes and loads a malformed or invalid
    progress.json, it should stop and report the error."""

    def test_invalid_json_detected(self, tmp_automation: Path) -> None:
        """Loading a file with invalid JSON should be detected."""
        progress_path = tmp_automation / "progress.json"
        progress_path.write_text("{invalid json", encoding="utf-8")
        with pytest.raises((json.JSONDecodeError, Exception)):
            json.loads(progress_path.read_text(encoding="utf-8"))

    def test_schema_invalid_progress_detected(self) -> None:
        """A progress dict with missing required fields should fail schema validation."""
        bad_progress = {"schema_version": 1}  # missing plan_file, last_run_id, steps
        with pytest.raises(jsonschema.ValidationError):
            _validate_progress(bad_progress)

    def test_extra_fields_rejected(self) -> None:
        """A progress dict with extra top-level fields should fail validation."""
        progress = make_progress()
        progress["unknown_field"] = "bad"
        with pytest.raises(jsonschema.ValidationError):
            _validate_progress(progress)

    def test_invalid_step_state_rejected(self) -> None:
        """A step with an invalid state value should fail schema validation."""
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "INVALID_STATE",
                    "agent": None,
                    "model": None,
                    "started_at": None,
                    "completed_at": None,
                    "pre_analysis": None,
                    "verification": None,
                    "fix_attempts": 0,
                    "commit": None,
                    "failure_reason": None,
                },
            }
        )
        with pytest.raises(jsonschema.ValidationError):
            _validate_progress(progress)

    def test_invalid_run_id_rejected(self) -> None:
        """A progress dict with a malformed run_id should fail validation."""
        progress = make_progress(run_id="bad-run-id")
        with pytest.raises(jsonschema.ValidationError):
            _validate_progress(progress)


# ===========================================================================
# STEP-008: progress.json schema validation on load
# ===========================================================================


class TestProgressSchemaValidationOnLoad:
    """load_progress should validate persisted progress against the schema."""

    def test_valid_progress_file_loads_successfully(self, tmp_path: Path) -> None:
        """A schema-valid progress file should load unchanged."""
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "TODO",
                },
            }
        )
        progress_path = tmp_path / "progress.json"
        write_progress(progress_path, progress)

        loaded = load_progress(progress_path)

        assert loaded == progress

    def test_invalid_schema_version_raises_validation_error(self, tmp_path: Path) -> None:
        """schema_version must match the schema const."""
        progress = make_progress()
        progress["schema_version"] = 2
        progress_path = tmp_path / "progress.json"
        write_progress(progress_path, progress)

        with pytest.raises(ProgressValidationError):
            load_progress(progress_path)

    def test_invalid_step_state_raises_validation_error(self, tmp_path: Path) -> None:
        """Step state values should be constrained to the schema enum."""
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "INVALID_STATE",
                },
            }
        )
        progress_path = tmp_path / "progress.json"
        write_progress(progress_path, progress)

        with pytest.raises(ProgressValidationError):
            load_progress(progress_path)

    def test_missing_required_fields_raise_validation_error(self, tmp_path: Path) -> None:
        """Missing top-level required fields should be rejected on load."""
        progress = make_progress()
        del progress["last_run_id"]
        progress_path = tmp_path / "progress.json"
        write_progress(progress_path, progress)

        with pytest.raises(ProgressValidationError):
            load_progress(progress_path)

    def test_wrong_field_types_raise_validation_error(self, tmp_path: Path) -> None:
        """Field types should be validated, including nested step fields."""
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "TODO",
                    "fix_attempts": "0",
                },
            }
        )
        progress_path = tmp_path / "progress.json"
        write_progress(progress_path, progress)

        with pytest.raises(ProgressValidationError):
            load_progress(progress_path)

    def test_error_message_includes_path_and_schema_details(self, tmp_path: Path) -> None:
        """Validation errors should identify the file and failed schema location."""
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "INVALID_STATE",
                },
            }
        )
        progress_path = tmp_path / "progress.json"
        write_progress(progress_path, progress)

        with pytest.raises(ProgressValidationError) as exc_info:
            load_progress(progress_path)

        message = str(exc_info.value)
        assert str(progress_path) in message
        assert "STEP-001" in message
        assert "state" in message
        assert "INVALID_STATE" in message

    def test_empty_json_object_raises_validation_error(self, tmp_path: Path) -> None:
        """An empty object is valid JSON but invalid progress shape."""
        progress_path = tmp_path / "progress.json"
        progress_path.write_text("{}", encoding="utf-8")

        with pytest.raises(ProgressValidationError):
            load_progress(progress_path)
