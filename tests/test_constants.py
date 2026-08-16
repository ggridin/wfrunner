"""Regression tests for tools.constants exact values.

Imports are deferred to test-function scope so this file collects
even before tools/constants.py is created (STEP-002).
"""

from __future__ import annotations

from pathlib import Path


class TestPreAnalysisFieldConstants:
    def test_prompt_truncation_field_constants_are_removed(self) -> None:
        import tools.constants as c

        assert not hasattr(c, "PA_FIELD_INCLUDE_OUTPUT")
        assert not hasattr(c, "PA_FIELD_MAX_OUTPUT_CHARS")

    def test_pa_field_output_files_names_file_based_evidence_key(self) -> None:
        import tools.constants as c

        assert c.PA_FIELD_OUTPUT_FILES == "output_files"


class TestStopReasonConstants:
    def test_stop_all_complete_preserves_existing_value(self) -> None:
        import tools.constants as c

        assert c.STOP_ALL_COMPLETE == "ALL_STEPS_COMPLETE"


class TestAnalysisStepConstants:
    def test_analysis_step_type_constant_exists(self) -> None:
        import tools.constants as c

        assert c.STEP_TYPE_ANALYSIS == "ANALYSIS"

    def test_artifact_files_field_constant_exists(self) -> None:
        import tools.constants as c

        assert c.FIELD_ARTIFACT_FILES == "artifact_files"


class TestViolationReasonConstants:
    def test_violation_not_in_allowed_preserves_existing_reason(self) -> None:
        import tools.constants as c

        assert c.VIOLATION_NOT_IN_ALLOWED == "not_in_allowed_files"


class TestRemovedStopReasonConstants:
    def test_production_code_does_not_reference_stop_max_steps(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        offenders = [
            str(path.relative_to(repo_root))
            for path in (repo_root / "tools").rglob("*.py")
            if "STOP_MAX_STEPS" in path.read_text(encoding="utf-8")
        ]

        assert offenders == []
