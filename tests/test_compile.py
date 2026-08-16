"""Tests for compiled plan generation and drift guards."""

from __future__ import annotations

import hashlib
import json
import textwrap
from pathlib import Path

import pytest


def _write_plan(path: Path, title: str = "Compile me") -> None:
    path.write_text(
        textwrap.dedent(f"""\
            # Test Plan

            ## Project description

            This plan checks the compiled plan artifact contract.

            ## Implementation plan

            ### STEP-001 - {title}

            This step has human-readable implementation prose that should be
            preserved as the compiled step description.

            ```yaml
            schema_version: 1
            id: STEP-001
            title: {title}
            type: IMPLEMENTATION
            agent: default.wfrunner
            model: default
            allowed_files:
              - tools/__init__.py
            verification:
              commands:
                - "python -c \\"print(1)\\""
            retry:
              max_fix_attempts: 0
            ```
        """),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestCompiledPlanArtifact:
    """Compiled plans separate source Markdown from machine execution input."""

    def test_compile_plan_writes_required_artifact_shape(self, tmp_path: Path) -> None:
        from tools.plan_compiler import compile_plan

        plan_path = tmp_path / "plan.md"
        automation_dir = tmp_path / ".wfrunner" / "automation"
        _write_plan(plan_path)

        compiled_path = compile_plan(plan_path, automation_dir=automation_dir)
        compiled = json.loads(compiled_path.read_text(encoding="utf-8"))

        assert compiled_path == automation_dir / "plan.compiled.json"
        assert compiled["schema_version"] == 1
        assert compiled["source_file"] == str(plan_path)
        assert compiled["source_sha256"] == _sha256(plan_path)
        assert "compiled plan artifact contract" in compiled["plan_description"]
        assert [step["id"] for step in compiled["steps"]] == ["STEP-001"]
        assert compiled["steps"][0]["title"] == "Compile me"
        assert "human-readable implementation prose" in compiled["steps"][0]["prompt"]
        assert compiled["steps"][0]["metadata"]["id"] == "STEP-001"


class TestCompiledPlanDriftGuard:
    """Run/resume should stop when source Markdown no longer matches the compiled artifact."""

    def test_load_for_run_rejects_source_sha256_drift(self, tmp_path: Path) -> None:
        from tools.plan_compiler import CompiledPlanDriftError, compile_plan, load_compiled_plan_for_run

        plan_path = tmp_path / "plan.md"
        automation_dir = tmp_path / ".wfrunner" / "automation"
        _write_plan(plan_path)
        compile_plan(plan_path, automation_dir=automation_dir)
        _write_plan(plan_path, title="Edited after compile")

        with pytest.raises(CompiledPlanDriftError, match="recompile"):
            load_compiled_plan_for_run(plan_path, automation_dir=automation_dir)

    def test_load_for_run_auto_compiles_when_artifact_missing(self, tmp_path: Path) -> None:
        from tools.plan_compiler import load_compiled_plan_for_run

        plan_path = tmp_path / "plan.md"
        automation_dir = tmp_path / ".wfrunner" / "automation"
        _write_plan(plan_path)

        compiled = load_compiled_plan_for_run(plan_path, automation_dir=automation_dir)

        assert (automation_dir / "plan.compiled.json").exists()
        assert compiled["source_sha256"] == _sha256(plan_path)


class TestCompiledProgressAgreement:
    """Progress should be keyed to the compiled/source checksum agreement."""

    def test_progress_records_compiled_source_checksum(self, tmp_path: Path) -> None:
        from tools.orchestrator.progress_manager import init_compiled_progress
        from tools.plan_compiler import compile_plan

        plan_path = tmp_path / "plan.md"
        automation_dir = tmp_path / ".wfrunner" / "automation"
        _write_plan(plan_path)
        compiled_path = compile_plan(plan_path, automation_dir=automation_dir)
        compiled = json.loads(compiled_path.read_text(encoding="utf-8"))

        progress = init_compiled_progress(compiled)

        assert progress["source_file"] == compiled["source_file"]
        assert progress["source_sha256"] == compiled["source_sha256"]

    def test_progress_mismatch_requires_reset_or_recompile(self) -> None:
        from tools.orchestrator.progress_manager import ProgressPlanMismatchError, validate_progress_matches_compiled_plan

        compiled = {"source_file": "docs/implementation_9.md", "source_sha256": "new"}
        progress = {"source_file": "docs/implementation_9.md", "source_sha256": "old"}

        with pytest.raises(ProgressPlanMismatchError, match="reset|recompile"):
            validate_progress_matches_compiled_plan(progress, compiled)


# ---------------------------------------------------------------------------
# Phase 9b — compiled step prompt, review_guidance, and plan-context artifact
# ---------------------------------------------------------------------------


def _write_phase9b_plan(path: Path) -> None:
    """Write a plan whose task prose follows the YAML block (real-plan shape)."""
    path.write_text(
        textwrap.dedent("""\
            # Test Plan

            ## Project description

            WaterfallRunner Phase 9b materializes shared plan context once.

            ## Implementation plan

            ### STEP-001 - Ship the widget

            ```yaml
            schema_version: 1
            id: STEP-001
            title: Ship the widget
            type: IMPLEMENTATION
            agent: default.wfrunner
            model: default
            allowed_files:
              - tools/__init__.py
            verification:
              commands:
                - "python -c \\"print(1)\\""
            retry:
              max_fix_attempts: 0
            ```

            Source mapping: R9b.1.

            Build the widget so the worker gets its task prose directly:

            - Create the widget module.
            - Keep it importable.

            ### STEP-002 - Approve the widget

            ```yaml
            schema_version: 1
            id: STEP-002
            title: Approve the widget
            type: HUMAN_GATE
            review_guidance: Confirm the widget matches the approved design before proceeding.
            ```
        """),
        encoding="utf-8",
    )


class TestCompiledStepPromptAndReviewGuidance:
    """Phase 9b: the compiled step exposes agent-facing prompt prose and gate guidance."""

    def test_compiled_implementation_step_carries_prompt_from_body(self, tmp_path: Path) -> None:
        from tools.plan_compiler import compile_plan_data

        plan_path = tmp_path / "plan.md"
        _write_phase9b_plan(plan_path)

        compiled = compile_plan_data(plan_path)
        step = compiled["steps"][0]

        assert "prompt" in step
        assert "Build the widget" in step["prompt"]
        assert "Create the widget module." in step["prompt"]
        # The YAML metadata block must not leak into the agent-facing prompt.
        assert "schema_version:" not in step["prompt"]
        assert "allowed_files:" not in step["prompt"]

    def test_compiled_human_gate_carries_review_guidance(self, tmp_path: Path) -> None:
        from tools.plan_compiler import compile_plan_data

        plan_path = tmp_path / "plan.md"
        _write_phase9b_plan(plan_path)

        compiled = compile_plan_data(plan_path)
        gate = compiled["steps"][1]

        assert gate["id"] == "STEP-002"
        assert gate["review_guidance"] == (
            "Confirm the widget matches the approved design before proceeding."
        )


class TestCompiledPlanContextArtifact:
    """Phase 9b: the shared plan context is materialized once as a runtime artifact."""

    def test_compile_writes_plan_context_artifact(self, tmp_path: Path) -> None:
        from tools.plan_compiler import PLAN_CONTEXT_FILENAME, compile_plan

        plan_path = tmp_path / "plan.md"
        automation_dir = tmp_path / ".wfrunner" / "automation"
        _write_phase9b_plan(plan_path)

        compile_plan(plan_path, automation_dir=automation_dir)

        context_path = automation_dir / PLAN_CONTEXT_FILENAME
        assert context_path.is_file()
        assert "materializes shared plan context" in context_path.read_text(encoding="utf-8")


class TestCompiledPromptValidation:
    """Compiled worker context must not be empty for agent-backed work."""

    def test_compile_rejects_empty_project_description(self, tmp_path: Path) -> None:
        from tools.plan_compiler import CompiledPlanError, compile_plan_data

        plan_path = tmp_path / "plan.md"
        plan_path.write_text(
            textwrap.dedent("""\
                # Test Plan

                ## Project description

                ## Implementation plan

                ### STEP-001 - Do work

                ```yaml
                schema_version: 1
                id: STEP-001
                title: Do work
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

                Implement the work.
            """),
            encoding="utf-8",
        )

        with pytest.raises(CompiledPlanError, match="Project description"):
            compile_plan_data(plan_path)

    def test_compile_rejects_empty_implementation_task_prose(self, tmp_path: Path) -> None:
        from tools.plan_compiler import CompiledPlanError, compile_plan_data

        plan_path = tmp_path / "plan.md"
        plan_path.write_text(
            textwrap.dedent("""\
                # Test Plan

                ## Project description

                This plan has context.

                ## Implementation plan

                ### STEP-001 - Do work

                ```yaml
                schema_version: 1
                id: STEP-001
                title: Do work
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
            """),
            encoding="utf-8",
        )

        with pytest.raises(CompiledPlanError, match="STEP-001.*task prose"):
            compile_plan_data(plan_path)

    def test_compile_rejects_empty_agent_backed_analysis_task_prose(self, tmp_path: Path) -> None:
        from tools.plan_compiler import CompiledPlanError, compile_plan_data

        plan_path = tmp_path / "plan.md"
        plan_path.write_text(
            textwrap.dedent("""\
                # Test Plan

                ## Project description

                This plan has context.

                ## Implementation plan

                ### STEP-001 - Analyze work

                ```yaml
                schema_version: 1
                id: STEP-001
                title: Analyze work
                type: ANALYSIS
                artifact_files:
                  - .wfrunner/analysis/report.md
                agent: default.wfrunner
                model: default
                ```
            """),
            encoding="utf-8",
        )

        with pytest.raises(CompiledPlanError, match="STEP-001.*task prose"):
            compile_plan_data(plan_path)

    def test_compile_allows_empty_command_only_analysis_task_prose(self, tmp_path: Path) -> None:
        from tests.helpers import make_analysis_step, make_plan
        from tools.plan_compiler import compile_plan_data

        plan_path = tmp_path / "plan.md"
        plan_path.write_text(
            make_plan(
                make_analysis_step(
                    step_id="STEP-001",
                    title="Analyze work",
                    pre_analysis={
                        "commands": [
                            {
                                "id": "collect-report",
                                "run": "echo ok",
                                "purpose": "Collect report.",
                                "fail_on_nonzero": True,
                            }
                        ]
                    },
                )
            ),
            encoding="utf-8",
        )

        compiled = compile_plan_data(plan_path)

        assert compiled["steps"][0]["prompt"] == ""