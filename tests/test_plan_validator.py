"""Tests for tools.plan_validator — covers VAL-001 through VAL-016 and PROT-001 through PROT-004."""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from tools.plan_parser import parse_plan
from tools.plan_validator import validate_plan, ValidationResult
from tools.wfrunner import main as wfrunner_main

# We use test helpers: make_implementation_step, make_human_gate_step, make_plan
from tests.helpers import make_analysis_step, make_implementation_step, make_human_gate_step, make_plan

TEST_PROTECTED_PATHS = (
    "schemas/",
    "tools/validate_plan.py",
    "tools/run_plan.py",
    ".github/agents/",
    ".github/copilot-instructions.md",
    "prompts/",
    ".wfrunner/wfrunner.toml",
)


@pytest.fixture
def schemas_dir() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent / "schemas"


# ---------------------------------------------------------------------------
# VAL-001: Valid minimal IMPLEMENTATION step
# ---------------------------------------------------------------------------


class TestVAL001:
    def test_valid_implementation_step(self, schemas_dir: pathlib.Path) -> None:
        plan_text = make_plan(
            make_implementation_step(step_id="STEP-001", title="Do something"),
        )
        result = validate_plan(parse_plan(plan_text), schemas_dir=schemas_dir)
        assert result.ok, f"Expected valid but got errors: {result.errors}"


# ---------------------------------------------------------------------------
# VAL-002: Valid minimal HUMAN_GATE step
# ---------------------------------------------------------------------------


class TestVAL002:
    def test_valid_human_gate_step(self, schemas_dir: pathlib.Path) -> None:
        plan_text = make_plan(
            make_human_gate_step(step_id="STEP-001", title="Review things"),
        )
        result = validate_plan(parse_plan(plan_text), schemas_dir=schemas_dir)
        assert result.ok, f"Expected valid but got errors: {result.errors}"


# ---------------------------------------------------------------------------
# VAL-003: Missing YAML metadata block
# ---------------------------------------------------------------------------


class TestVAL003:
    def test_missing_yaml_block(self, schemas_dir: pathlib.Path) -> None:
        plan_text = textwrap.dedent("""\
            # Plan

            ## Implementation plan

            ### STEP-001 — Missing YAML

            No YAML block at all.
        """)
        parse_result = parse_plan(plan_text)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert not result.ok


# ---------------------------------------------------------------------------
# VAL-004: Malformed YAML
# ---------------------------------------------------------------------------


class TestVAL004:
    def test_malformed_yaml(self, schemas_dir: pathlib.Path) -> None:
        plan_text = textwrap.dedent("""\
            # Plan

            ### STEP-001 — Bad YAML

            ```yaml
            schema_version: 1
            id: STEP-001
            title: Bad YAML
            type: [unclosed
            ```
        """)
        parse_result = parse_plan(plan_text)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert not result.ok


# ---------------------------------------------------------------------------
# VAL-005: Unknown field in step metadata
# ---------------------------------------------------------------------------


class TestVAL005:
    def test_unknown_field(self, schemas_dir: pathlib.Path) -> None:
        plan_text = make_plan(
            make_human_gate_step(step_id="STEP-001", title="Review"),
        )
        # Inject an unknown field into the YAML
        plan_text = plan_text.replace(
            "type: HUMAN_GATE",
            "type: HUMAN_GATE\nunknown_field: oops",
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert not result.ok
        assert any("unknown_field" in e.message.lower() or "additional" in e.message.lower()
                    for e in result.errors)


# ---------------------------------------------------------------------------
# VAL-006: Duplicate step ID
# ---------------------------------------------------------------------------


class TestVAL006:
    def test_duplicate_step_id(self, schemas_dir: pathlib.Path) -> None:
        plan_text = make_plan(
            make_human_gate_step(step_id="STEP-001", title="First"),
            make_human_gate_step(step_id="STEP-001", title="First"),
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert not result.ok
        assert any("Duplicate" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# VAL-007: Non-contiguous step IDs
# ---------------------------------------------------------------------------


class TestVAL007:
    def test_non_contiguous_step_ids(self, schemas_dir: pathlib.Path) -> None:
        plan_text = make_plan(
            make_human_gate_step(step_id="STEP-001", title="First"),
            make_human_gate_step(step_id="STEP-003", title="Third"),
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert not result.ok
        assert any("out of order" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# VAL-008: Step IDs out of order
# ---------------------------------------------------------------------------


class TestVAL008:
    def test_step_ids_out_of_order(self, schemas_dir: pathlib.Path) -> None:
        plan_text = make_plan(
            make_human_gate_step(step_id="STEP-002", title="Second"),
            make_human_gate_step(step_id="STEP-001", title="First"),
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert not result.ok


# ---------------------------------------------------------------------------
# VAL-009: Heading ID differs from YAML ID
# ---------------------------------------------------------------------------


class TestVAL009:
    def test_heading_id_differs_from_yaml_id(self, schemas_dir: pathlib.Path) -> None:
        plan_text = textwrap.dedent("""\
            # Plan

            ### STEP-001 — Mismatched

            ```yaml
            schema_version: 1
            id: STEP-999
            title: Mismatched
            type: HUMAN_GATE
            ```
        """)
        parse_result = parse_plan(plan_text)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert not result.ok
        assert any("differs from YAML id" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# VAL-010: Heading title differs from YAML title
# ---------------------------------------------------------------------------


class TestVAL010:
    def test_heading_title_differs_from_yaml_title(self, schemas_dir: pathlib.Path) -> None:
        plan_text = textwrap.dedent("""\
            # Plan

            ### STEP-001 — Heading Title

            ```yaml
            schema_version: 1
            id: STEP-001
            title: YAML Title
            type: HUMAN_GATE
            ```
        """)
        parse_result = parse_plan(plan_text)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert not result.ok
        assert any("differs from YAML title" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# VAL-011: IMPLEMENTATION missing allowed_files
# ---------------------------------------------------------------------------


class TestVAL011:
    def test_implementation_missing_allowed_files(self, schemas_dir: pathlib.Path) -> None:
        plan_text = textwrap.dedent("""\
            # Plan

            ### STEP-001 — No allowed files

            ```yaml
            schema_version: 1
            id: STEP-001
            title: No allowed files
            type: IMPLEMENTATION
            agent: default.wfrunner
            model: default
            verification:
              commands:
                - "python -c 1"
            retry:
              max_fix_attempts: 0
            ```
        """)
        parse_result = parse_plan(plan_text)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert not result.ok
        assert any("allowed_files" in e.message for e in result.errors)


class TestVerificationCommandsSchema:
        def test_empty_verification_commands_are_schema_valid(
                self,
                schemas_dir: pathlib.Path,
        ) -> None:
                plan_text = textwrap.dedent("""\
                        # Plan

                        ### STEP-001 — No command verification

                        ```yaml
                        schema_version: 1
                        id: STEP-001
                        title: No command verification
                        type: IMPLEMENTATION
                        agent: default.wfrunner
                        model: default
                        allowed_files:
                            - tools/__init__.py
                        verification:
                            commands: []
                        retry:
                            max_fix_attempts: 0
                        ```
                """)
                parse_result = parse_plan(plan_text)
                assert parse_result.steps[0].yaml_block["verification"]["commands"] == []

                result = validate_plan(parse_result, schemas_dir=schemas_dir)

                assert result.ok, f"Expected empty verification command list to validate: {result.errors}"


class TestPreAnalysisFileBasedOutputSchema:
    def test_pre_analysis_command_accepts_declared_output_files_without_prompt_fields(
        self,
        schemas_dir: pathlib.Path,
    ) -> None:
        plan_text = textwrap.dedent("""\
            # Plan

            ### STEP-001 — File based pre-analysis

            ```yaml
            schema_version: 1
            id: STEP-001
            title: File based pre-analysis
            type: IMPLEMENTATION
            agent: default.wfrunner
            model: default
            allowed_files:
              - tools/__init__.py
            pre_analysis:
              commands:
                - id: coverage-report
                  run: 'python -m pytest --cov=tools --cov-report=xml:.wfrunner/analysis/coverage.xml'
                  purpose: Generate coverage evidence.
                  fail_on_nonzero: true
                  output_files:
                    - .wfrunner/analysis/coverage.xml
            verification:
              commands: []
            retry:
              max_fix_attempts: 0
            ```
        """)
        parse_result = parse_plan(plan_text)

        result = validate_plan(parse_result, schemas_dir=schemas_dir)

        assert result.ok, f"Expected output_files pre-analysis command to validate: {result.errors}"

    def test_pre_analysis_prompt_truncation_fields_are_rejected(
        self,
        schemas_dir: pathlib.Path,
    ) -> None:
        plan_text = make_plan(
            make_implementation_step(
                step_id="STEP-001",
                title="Prompt truncation fields",
                pre_analysis={
                    "commands": [
                        {
                            "id": "old-prompt-output",
                            "run": "echo old",
                            "purpose": "Old prompt output path.",
                            "fail_on_nonzero": True,
                            "include_output_in_prompt": True,
                            "max_output_chars": 100,
                        },
                    ],
                },
            ),
        )
        parse_result = parse_plan(plan_text)

        result = validate_plan(parse_result, schemas_dir=schemas_dir)

        assert not result.ok
        assert any(
            "include_output_in_prompt" in error.message or "max_output_chars" in error.message
            for error in result.errors
        )


class TestAnalysisStepSchema:
    def test_analysis_step_accepts_artifact_files_without_allowed_files(
        self,
        schemas_dir: pathlib.Path,
    ) -> None:
        plan_text = make_plan(
            make_analysis_step(
                step_id="STEP-001",
                title="Package smoke analysis",
                artifact_files=[".wfrunner/analysis/package-smoke.md"],
                pre_analysis={
                    "commands": [
                        {
                            "id": "smoke-report",
                            "run": "python build.py",
                            "purpose": "Generate package smoke evidence.",
                            "fail_on_nonzero": True,
                            "output_files": [".wfrunner/analysis/package-smoke.md"],
                        },
                    ],
                },
            ),
        )
        parse_result = parse_plan(plan_text)

        result = validate_plan(parse_result, schemas_dir=schemas_dir)

        assert result.ok, f"Expected ANALYSIS step to validate: {result.errors}"

    def test_analysis_step_rejects_allowed_files(
        self,
        schemas_dir: pathlib.Path,
    ) -> None:
        plan_text = make_plan(
            make_analysis_step(
                step_id="STEP-001",
                title="Analysis with source scope",
                extra_yaml="allowed_files:\n  - tools/run_plan.py",
            ),
        )
        parse_result = parse_plan(plan_text)

        result = validate_plan(parse_result, schemas_dir=schemas_dir)

        assert not result.ok
        assert any("allowed_files" in error.message for error in result.errors)

    def test_implementation_rejects_empty_allowed_files(
        self,
        schemas_dir: pathlib.Path,
    ) -> None:
        plan_text = textwrap.dedent("""\
            # Plan

            ### STEP-001 — Empty implementation scope

            ```yaml
            schema_version: 1
            id: STEP-001
            title: Empty implementation scope
            type: IMPLEMENTATION
            agent: default.wfrunner
            model: default
            allowed_files: []
            verification:
              commands: []
            retry:
              max_fix_attempts: 0
            ```
        """)
        parse_result = parse_plan(plan_text)

        result = validate_plan(parse_result, schemas_dir=schemas_dir)

        assert not result.ok
        assert any("allowed_files" in error.message for error in result.errors)


# ---------------------------------------------------------------------------
# VAL-012 through VAL-016: Removed fields
# ---------------------------------------------------------------------------


class TestRemovedFields:
    """VAL-012 through VAL-016: Steps with removed fields should fail validation."""

    @pytest.mark.parametrize(
        "field_name,val_id",
        [
            ("state", "VAL-012"),
            ("depends_on", "VAL-013"),
            ("review", "VAL-014"),
            ("risk", "VAL-015"),
            ("human_gate", "VAL-016"),
        ],
    )
    def test_removed_field_rejected(
        self, field_name: str, val_id: str, schemas_dir: pathlib.Path
    ) -> None:
        plan_text = make_plan(
            make_implementation_step(
                step_id="STEP-001",
                title="With removed field",
                extra_yaml=f"{field_name}: some_value\n",
            ),
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert not result.ok, f"{val_id}: '{field_name}' should be rejected"


# ---------------------------------------------------------------------------
# PROT-001: Step modifies protected file without prior HUMAN_GATE
# ---------------------------------------------------------------------------


class TestProtectedPathsOptional:
    def test_none_protected_paths_skips_protected_path_validation(
        self,
        schemas_dir: pathlib.Path,
    ) -> None:
        plan_text = make_plan(
            make_implementation_step(
                step_id="STEP-001",
                title="Touch agents",
                allowed_files=[".github/agents/new-agent.md"],
            ),
        )
        parse_result = parse_plan(plan_text)

        result = validate_plan(
            parse_result,
            schemas_dir=schemas_dir,
            protected_paths=None,
        )

        assert result.ok, f"Expected protected-path validation to be skipped: {result.errors}"


class TestPROT001:
    def test_protected_file_without_human_gate(self, schemas_dir: pathlib.Path) -> None:
        plan_text = make_plan(
            make_implementation_step(
                step_id="STEP-001",
                title="Touch schemas",
                allowed_files=["schemas/implementation-step.schema.json"],
            ),
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(
            parse_result,
            schemas_dir=schemas_dir,
            protected_paths=TEST_PROTECTED_PATHS,
        )
        assert not result.ok
        assert any("protected" in e.message.lower() for e in result.errors)

    def test_run_plan_without_human_gate_fails_with_default_protected_paths(
        self,
        schemas_dir: pathlib.Path,
    ) -> None:
        plan_text = make_plan(
            make_implementation_step(
                step_id="STEP-001",
                title="Touch run plan",
                allowed_files=["tools/run_plan.py"],
            ),
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(
            parse_result,
            schemas_dir=schemas_dir,
            protected_paths=TEST_PROTECTED_PATHS,
        )
        assert not result.ok
        assert any("protected" in e.message.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# PROT-002: Step modifies schemas/ after immediately preceding HUMAN_GATE
# ---------------------------------------------------------------------------


class TestPROT002:
    def test_protected_file_with_preceding_human_gate(self, schemas_dir: pathlib.Path) -> None:
        plan_text = make_plan(
            make_human_gate_step(step_id="STEP-001", title="Review schemas"),
            make_implementation_step(
                step_id="STEP-002",
                title="Update schema",
                allowed_files=["schemas/new-schema.json"],
            ),
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(
            parse_result,
            schemas_dir=schemas_dir,
            protected_paths=TEST_PROTECTED_PATHS,
        )
        assert result.ok, f"Expected valid but got errors: {result.errors}"


# ---------------------------------------------------------------------------
# PROT-003: Step modifies .github/agents/ without prior HUMAN_GATE
# ---------------------------------------------------------------------------


class TestPROT003:
    def test_agents_dir_without_human_gate(self, schemas_dir: pathlib.Path) -> None:
        plan_text = make_plan(
            make_implementation_step(
                step_id="STEP-001",
                title="Touch agents",
                allowed_files=[".github/agents/new-agent.md"],
            ),
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(
            parse_result,
            schemas_dir=schemas_dir,
            protected_paths=TEST_PROTECTED_PATHS,
        )
        assert not result.ok
        assert any("protected" in e.message.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# PROT-004: Human gate exists but not immediately before protected change
# ---------------------------------------------------------------------------


class TestPROT004:
    def test_no_human_gate_before_protected_step(self, schemas_dir: pathlib.Path) -> None:
        """PROT-004: A HUMAN_GATE exists in the plan but only *after* the protected step."""
        plan_text = make_plan(
            make_implementation_step(
                step_id="STEP-001",
                title="Touch schemas first",
                allowed_files=["schemas/test.json"],
            ),
            make_human_gate_step(step_id="STEP-002", title="Review"),
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(
            parse_result,
            schemas_dir=schemas_dir,
            protected_paths=TEST_PROTECTED_PATHS,
        )
        assert not result.ok
        assert any("protected" in e.message.lower() for e in result.errors)

    def test_gate_before_protected_step_passes(self, schemas_dir: pathlib.Path) -> None:
        """A gate exists before (not immediately) the protected step — allowed."""
        plan_text = make_plan(
            make_human_gate_step(step_id="STEP-001", title="Review"),
            make_implementation_step(
                step_id="STEP-002",
                title="Normal step",
                allowed_files=["tools/__init__.py"],
            ),
            make_implementation_step(
                step_id="STEP-003",
                title="Touch schemas",
                allowed_files=["schemas/test.json"],
            ),
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(
            parse_result,
            schemas_dir=schemas_dir,
            protected_paths=TEST_PROTECTED_PATHS,
        )
        assert result.ok, f"Expected valid but got errors: {result.errors}"


# ---------------------------------------------------------------------------
# Validate the actual implementation plan
# ---------------------------------------------------------------------------


class TestRealPlan:
    def test_implementation_plan_is_valid(self, schemas_dir: pathlib.Path) -> None:
        plan_path = pathlib.Path(__file__).resolve().parent.parent / "docs" / "implementation-plan.md"
        if not plan_path.exists():
            pytest.skip("implementation-plan.md not found")
        from tools.plan_parser import parse_plan_file
        parse_result = parse_plan_file(plan_path)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert result.ok, f"Plan should be valid but got errors: {[e.message for e in result.errors]}"


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestValidatePlanCLI:
    def test_cli_valid_plan(self, tmp_path: pathlib.Path) -> None:
        plan_text = make_plan(
            make_human_gate_step(step_id="STEP-001", title="Review"),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        exit_code = wfrunner_main(["validate", str(plan_file)])
        assert exit_code == 0

    def test_cli_invalid_plan(self, tmp_path: pathlib.Path) -> None:
        plan_text = textwrap.dedent("""\
            # Plan

            ### STEP-001 — Broken

            ```yaml
            schema_version: 1
            id: STEP-001
            title: Broken
            type: INVALID_TYPE
            ```
        """)
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        exit_code = wfrunner_main(["validate", str(plan_file)])
        assert exit_code == 1

    def test_cli_no_args(self) -> None:
        assert wfrunner_main([]) == 2

    def test_cli_file_not_found(self) -> None:
        assert wfrunner_main(["validate", "nonexistent-file.md"]) == 2

    def test_cli_missing_plan_with_no_steps(self, tmp_path: pathlib.Path) -> None:
        plan_file = tmp_path / "empty.md"
        plan_file.write_text("# Empty plan\n", encoding="utf-8")

        exit_code = wfrunner_main(["validate", str(plan_file)])
        assert exit_code == 1  # No steps found should be an error


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestValidationEdgeCases:
    def test_mixed_step_types(self, schemas_dir: pathlib.Path) -> None:
        plan_text = make_plan(
            make_human_gate_step(step_id="STEP-001", title="Gate one"),
            make_implementation_step(step_id="STEP-002", title="Impl step"),
            make_human_gate_step(step_id="STEP-003", title="Gate two"),
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert result.ok

    def test_empty_parse_result(self, schemas_dir: pathlib.Path) -> None:
        from tools.plan_parser import ParseResult
        result = validate_plan(ParseResult(), schemas_dir=schemas_dir)
        assert not result.ok
        assert any("No steps" in e.message for e in result.errors)

    def test_validation_result_ok_property(self) -> None:
        r = ValidationResult()
        assert r.ok
        r.add("STEP-001", "test error")
        assert not r.ok


# ---------------------------------------------------------------------------
# Minor step ID validation (STEP-NNN.NNN)
# ---------------------------------------------------------------------------


class TestMinorStepIDValidation:
    """Tests for validator handling of minor (sub-step) IDs."""

    def test_valid_plan_with_minor_steps(self, schemas_dir: pathlib.Path) -> None:
        """STEP-001, STEP-002, STEP-002.001, STEP-002.002, STEP-003 is valid."""
        plan_text = make_plan(
            make_human_gate_step(step_id="STEP-001", title="First"),
            make_human_gate_step(step_id="STEP-002", title="Second"),
            make_human_gate_step(step_id="STEP-002.001", title="Sub one"),
            make_human_gate_step(step_id="STEP-002.002", title="Sub two"),
            make_human_gate_step(step_id="STEP-003", title="Third"),
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert result.ok, f"Expected valid but got errors: {[e.message for e in result.errors]}"

    def test_minor_step_before_bare_major_rejected(self, schemas_dir: pathlib.Path) -> None:
        """STEP-002.001 appearing before STEP-002 (bare major) is rejected."""
        plan_text = make_plan(
            make_human_gate_step(step_id="STEP-001", title="First"),
            make_human_gate_step(step_id="STEP-002.001", title="Sub before major"),
            make_human_gate_step(step_id="STEP-002", title="Second"),
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert not result.ok

    def test_gap_in_minor_ids_rejected(self, schemas_dir: pathlib.Path) -> None:
        """STEP-002.001 then STEP-002.003 (gap — missing .002) is rejected."""
        plan_text = make_plan(
            make_human_gate_step(step_id="STEP-001", title="First"),
            make_human_gate_step(step_id="STEP-002", title="Second"),
            make_human_gate_step(step_id="STEP-002.001", title="Sub one"),
            make_human_gate_step(step_id="STEP-002.003", title="Sub three"),
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert not result.ok

    def test_minor_under_nonexistent_major_rejected(self, schemas_dir: pathlib.Path) -> None:
        """STEP-002.001 without a preceding STEP-002 is rejected."""
        plan_text = make_plan(
            make_human_gate_step(step_id="STEP-001", title="First"),
            make_human_gate_step(step_id="STEP-002.001", title="Orphan sub"),
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert not result.ok

    def test_only_major_steps_still_valid(self, schemas_dir: pathlib.Path) -> None:
        """A plan with only major steps (no minors) validates as before."""
        plan_text = make_plan(
            make_human_gate_step(step_id="STEP-001", title="First"),
            make_human_gate_step(step_id="STEP-002", title="Second"),
            make_human_gate_step(step_id="STEP-003", title="Third"),
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert result.ok, f"Expected valid but got errors: {[e.message for e in result.errors]}"


# ---------------------------------------------------------------------------
# HUMAN_GATE pre_analysis schema validation
# ---------------------------------------------------------------------------


class TestHumanGatePreAnalysisSchema:
    """Verify JSON Schema accepts pre_analysis on HUMAN_GATE steps."""

    def test_human_gate_with_pre_analysis_passes_schema(self, schemas_dir: pathlib.Path) -> None:
        """A HUMAN_GATE step that includes a pre_analysis block should validate."""
        plan_text = make_plan(
            textwrap.dedent("""\
                ### STEP-001 — Gate with analysis

                ```yaml
                schema_version: 1
                id: STEP-001
                title: Gate with analysis
                type: HUMAN_GATE
                review_guidance: Review with diagnostics.
                pre_analysis:
                  commands:
                    - id: check-tests
                      run: 'python -m pytest tests -q'
                      purpose: Run tests before human review
                      fail_on_nonzero: true
                ```
            """),
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert result.ok, f"Expected valid but got errors: {result.errors}"

    def test_human_gate_without_pre_analysis_still_valid(self, schemas_dir: pathlib.Path) -> None:
        """A HUMAN_GATE step without pre_analysis validates (field is optional)."""
        plan_text = make_plan(
            make_human_gate_step(step_id="STEP-001", title="Plain gate"),
        )
        parse_result = parse_plan(plan_text)
        result = validate_plan(parse_result, schemas_dir=schemas_dir)
        assert result.ok, f"Expected valid but got errors: {result.errors}"


# ---------------------------------------------------------------------------
# Phase 9b — retired prompt field and HUMAN_GATE review_guidance
# ---------------------------------------------------------------------------


class TestPhase9bStepSchema:
    """The step schema drops the prompt template-path and uses review_guidance."""

    def test_implementation_step_without_prompt_is_valid(self, schemas_dir: pathlib.Path) -> None:
        plan_text = make_plan(
            make_implementation_step(step_id="STEP-001", title="No prompt path"),
        )
        result = validate_plan(parse_plan(plan_text), schemas_dir=schemas_dir)
        assert result.ok, f"Expected valid but got errors: {[e.message for e in result.errors]}"

    def test_implementation_step_with_prompt_field_is_rejected(self, schemas_dir: pathlib.Path) -> None:
        plan_text = textwrap.dedent("""\
            # Plan

            ### STEP-001 — Retired prompt field

            ```yaml
            schema_version: 1
            id: STEP-001
            title: Retired prompt field
            type: IMPLEMENTATION
            agent: default.wfrunner
            prompt: prompts/implement-step.md
            model: default
            allowed_files:
              - tools/__init__.py
            verification:
              commands:
                - "python -c 1"
            retry:
              max_fix_attempts: 0
            ```
        """)
        result = validate_plan(parse_plan(plan_text), schemas_dir=schemas_dir)
        assert not result.ok
        assert any("prompt" in e.message for e in result.errors)

    def test_human_gate_with_review_guidance_is_valid(self, schemas_dir: pathlib.Path) -> None:
        plan_text = make_plan(
            make_human_gate_step(
                step_id="STEP-001",
                title="Gate",
                review_guidance="Review the protected change before approving.",
            ),
        )
        result = validate_plan(parse_plan(plan_text), schemas_dir=schemas_dir)
        assert result.ok, f"Expected valid but got errors: {[e.message for e in result.errors]}"

    def test_human_gate_with_description_field_is_rejected(self, schemas_dir: pathlib.Path) -> None:
        plan_text = textwrap.dedent("""\
            # Plan

            ### STEP-001 — Retired description field

            ```yaml
            schema_version: 1
            id: STEP-001
            title: Retired description field
            type: HUMAN_GATE
            description: Review the change.
            ```
        """)
        result = validate_plan(parse_plan(plan_text), schemas_dir=schemas_dir)
        assert not result.ok
        assert any("description" in e.message for e in result.errors)
