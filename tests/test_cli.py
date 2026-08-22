"""Tests for the CLI interface (tools/run_plan.py)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest

from tests.fake_agent import FakeAgentAdapter
from tests.helpers import (
    make_analysis_step,
    make_human_gate_step,
    make_default_config,
    make_implementation_step,
    make_plan,
    make_progress,
    write_progress,
)
from tools.config import GitConfig, WaterfallRunnerConfig
from tools.constants import EXIT_USAGE_VALIDATION_ERROR
from tools.orchestrator.change_detector import FakeChangeDetector
from tools.plan_parser import ParsedStep
from tools.run_plan import (
    PrepareError,
    RunContext,
    _verification_step_for_current_shell,
    prepare_run,
    run,
)


def _prepare_run_context(
    tmp_path: Path,
    *step_blocks: str,
    config: WaterfallRunnerConfig | None = None,
) -> RunContext:
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(make_plan(*step_blocks), encoding="utf-8")
    config = config or make_default_config(automation_dir=str(tmp_path / ".automation"))
    return prepare_run(str(plan_file), config)


class TestVerificationCommandQuoting:
    """Windows cmd.exe compatibility for plan-authored verification commands."""

    def test_single_quoted_keyword_expression_is_windows_shell_safe(
        self,
        tmp_path: Path,
    ) -> None:
        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step(
                "STEP-001",
                "Quoted pytest expression",
                verification_commands=[
                    '"python -m pytest tests/ -k \'not (excluded)\'"',
                    '"python -c \\"print(\'ok\')\\""',
                ],
            ),
        )
        step = ctx.steps[0]

        with mock.patch("tools.run_plan.sys.platform", "win32"):
            normalized_step = _verification_step_for_current_shell(step)

        commands = normalized_step.yaml_block["verification"]["commands"]
        assert commands[0] == 'python -m pytest tests/ -k "not (excluded)"'
        assert commands[1] == 'python -c "print(\'ok\')"'
        assert step.yaml_block["verification"]["commands"][0].endswith("'not (excluded)'")


# ---------------------------------------------------------------------------
# Plan-not-found / validation failure
# ---------------------------------------------------------------------------

class TestValidationErrors:
    """Verify graceful handling of missing or invalid plans."""

    def test_plan_not_found(self, tmp_path: Path) -> None:
        config = make_default_config(automation_dir=str(tmp_path / ".automation"))

        with pytest.raises(PrepareError, match="Plan file not found") as exc_info:
            prepare_run(str(tmp_path / "nonexistent.md"), config)

        assert exc_info.value.exit_code == EXIT_USAGE_VALIDATION_ERROR

    def test_invalid_plan_returns_2(self, tmp_path: Path) -> None:
        # Plan with a broken step (missing required fields).
        plan_text = "# Plan\n\n## Implementation plan\n\n### STEP-001 — Bad\n\n```yaml\nschema_version: 1\nid: STEP-001\ntitle: Bad\ntype: IMPLEMENTATION\n```\n"
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")
        config = make_default_config(automation_dir=str(tmp_path / ".automation"))
        with pytest.raises(PrepareError) as exc_info:
            prepare_run(str(plan_file), config)

        assert exc_info.value.exit_code == EXIT_USAGE_VALIDATION_ERROR


class TestNoScopeEnforcementFlag:
    def test_parser_accepts_flag(self) -> None:
        from tools.wfrunner import build_parser

        args = build_parser().parse_args(
            ["run", "docs/plan.md", "--no-scope-enforcement"]
        )

        assert args.no_scope_enforcement is True

    def test_run_handler_forwards_enabled_flag(self, tmp_path: Path) -> None:
        from tools.wfrunner import main

        plan_file = tmp_path / "plan.md"
        plan_file.write_text("", encoding="utf-8")
        config = make_default_config(automation_dir=str(tmp_path / ".automation"))
        ctx = mock.sentinel.run_context

        with (
            mock.patch("tools.wfrunner._load_run_config", return_value=config),
            mock.patch("tools.run_plan.prepare_run", return_value=ctx),
            mock.patch("tools.run_plan.run", return_value=0) as run_mock,
        ):
            exit_code = main(
                ["run", str(plan_file), "--no-scope-enforcement"]
            )

        assert exit_code == 0
        run_mock.assert_called_once_with(
            ctx,
            one_step=False,
            approve_human_gates=False,
            no_scope_enforcement=True,
        )


# ---------------------------------------------------------------------------
# Dirty-start blocking
# ---------------------------------------------------------------------------

class TestDirtyStartBlocking:
    """Verify dirty worktrees block implementation steps before execution."""

    def test_is_worktree_clean_uses_configured_git_timeout(self) -> None:
        from tools.run_plan import _is_worktree_clean

        config = make_default_config(git_timeout_seconds=45)

        with mock.patch("tools.orchestrator.git.subprocess.run") as subprocess_run:
            subprocess_run.return_value = mock.Mock(returncode=0, stdout="")
            assert _is_worktree_clean(config) is True

        subprocess_run.assert_called_once()
        assert subprocess_run.call_args.kwargs["timeout"] == 45

    def test_dirty_start_blocks_selected_step_before_pre_analysis_or_agent(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step(
                "STEP-001",
                "Dirty-start step",
                pre_analysis={
                    "commands": [
                        {
                            "id": "would-run",
                            "run": "python -c \"print(1)\"",
                            "purpose": "Should not run when the worktree starts dirty.",
                            "fail_on_nonzero": True,
                        },
                    ],
                },
            ),
        )

        with (
            mock.patch("tools.run_plan._is_worktree_clean", return_value=False),
            mock.patch(
                "tools.run_plan.run_pre_analysis",
                side_effect=AssertionError("pre-analysis should not run for a dirty-start step"),
            ),
        ):
            code = run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 1
        assert fake_agent.invocations == []

        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        step_progress = progress["steps"]["STEP-001"]
        assert step_progress["state"] == "BLOCKED"
        assert step_progress["failure_reason"]["code"] == "DIRTY_WORKTREE"

    def test_orchestration_dirty_worktree_check_receives_config(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        config = make_default_config(automation_dir=str(tmp_path / ".automation"))
        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step("STEP-001", "Config-aware clean check"),
            config=config,
        )
        fake_agent.enqueue_done("STEP-001")

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True) as clean_check:
            code = run(ctx, one_step=True, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        clean_check.assert_called_once_with(config)

    def test_clean_start_preserves_injected_adapter_and_change_detector(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step(
                "STEP-001",
                "Clean-start step",
                verification_commands=['"python -c \\"print(1)\\""'],
            ),
        )
        fake_agent.enqueue_done("STEP-001")

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True):
            code = run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        assert [request.step_id for request in fake_agent.invocations] == ["STEP-001"]

        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "DONE"


class TestAnalysisStepExecution:
    """ANALYSIS steps generate evidence without source-edit permission."""

    @staticmethod
    def _file_output_pre_analysis(artifact_path: Path) -> dict[str, list[dict[str, object]]]:
        return {
            "commands": [
                {
                    "id": "analysis-report",
                    "run": f"python -c \"from pathlib import Path; Path({str(artifact_path)!r}).write_text('ok', encoding='utf-8')\"",
                    "purpose": "Generate analysis evidence.",
                    "fail_on_nonzero": True,
                    "output_files": [str(artifact_path)],
                },
            ],
        }

    @staticmethod
    def _pre_analysis_result(*, ok: bool = True, tree_modified: bool = False) -> SimpleNamespace:
        return SimpleNamespace(
            ok=ok,
            command_results=[],
            tree_modified=tree_modified,
            failure_reason="Analysis modified Git-visible source files." if tree_modified else None,
        )

    def test_command_only_analysis_can_start_dirty_and_does_not_invoke_agent(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        artifact_path = tmp_path / ".wfrunner" / "analysis" / "report.md"
        ctx = _prepare_run_context(
            tmp_path,
            make_analysis_step(
                "STEP-001",
                "Command-only analysis",
                artifact_files=[str(artifact_path)],
                pre_analysis=self._file_output_pre_analysis(artifact_path),
            ),
        )

        with (
            mock.patch("tools.run_plan._is_worktree_clean", side_effect=AssertionError("ANALYSIS should not require a clean start")),
            mock.patch("tools.run_plan.run_pre_analysis", return_value=self._pre_analysis_result()) as run_pa,
        ):
            code = run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        assert fake_agent.invocations == []
        run_pa.assert_called_once()
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "DONE"

    def test_agentless_analysis_with_task_prompt_uses_default_agent(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        artifact_path = tmp_path / ".wfrunner" / "analysis" / "agent-report.md"
        config = make_default_config(
            automation_dir=str(tmp_path / ".automation"),
            default_agent="configured-analysis-agent",
        )
        step = make_analysis_step(
            "STEP-001",
            "Agentless analysis with prose",
            artifact_files=[str(artifact_path)],
        ) + "\nSummarize the current implementation risks.\n"
        ctx = _prepare_run_context(tmp_path, step, config=config)
        fake_agent.enqueue_done("STEP-001")

        with mock.patch(
            "tools.run_plan._is_worktree_clean",
            side_effect=AssertionError("ANALYSIS should not require a clean start"),
        ):
            code = run(ctx, one_step=True, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        assert len(fake_agent.invocations) == 1
        request = fake_agent.invocations[0]
        assert request.agent_name == "configured-analysis-agent"
        assert request.step_prompt == "Summarize the current implementation risks."
        assert Path(request.system_prompt_path).is_absolute()

    def test_analysis_agent_default_sentinel_resolves_to_configured_default(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        artifact_path = tmp_path / ".wfrunner" / "analysis" / "agent-report.md"
        ctx = _prepare_run_context(
            tmp_path,
            make_analysis_step(
                "STEP-001",
                "Agent default analysis",
                artifact_files=[str(artifact_path)],
                agent="default",
                model="default",
                task_prose="Summarize the current implementation risks.",
            ),
        )
        fake_agent.enqueue_done("STEP-001")

        with mock.patch(
            "tools.run_plan._is_worktree_clean",
            side_effect=AssertionError("ANALYSIS should not require a clean start"),
        ):
            code = run(ctx, one_step=True, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        request = fake_agent.invocations[0]
        assert request.agent_name == "default.wfrunner"
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["agent"] == "default.wfrunner"

    def test_agent_backed_analysis_invokes_agent_without_allowed_files(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        artifact_path = tmp_path / ".wfrunner" / "analysis" / "agent-report.md"
        ctx = _prepare_run_context(
            tmp_path,
            make_analysis_step(
                "STEP-001",
                "Agent-backed analysis",
                artifact_files=[str(artifact_path)],
                pre_analysis=self._file_output_pre_analysis(artifact_path),
                agent="default.wfrunner",
                model="default",
            ),
        )
        fake_agent.enqueue_done("STEP-001")

        with (
            mock.patch("tools.run_plan._is_worktree_clean", side_effect=AssertionError("ANALYSIS should not require a clean start")),
            mock.patch("tools.run_plan.run_pre_analysis", return_value=self._pre_analysis_result()),
        ):
            code = run(ctx, one_step=True, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        assert len(fake_agent.invocations) == 1
        assert fake_agent.invocations[0].allowed_files == []

    def test_analysis_fails_if_pre_analysis_modifies_git_visible_sources(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        artifact_path = tmp_path / ".wfrunner" / "analysis" / "report.md"
        ctx = _prepare_run_context(
            tmp_path,
            make_analysis_step(
                "STEP-001",
                "Mutating analysis",
                artifact_files=[str(artifact_path)],
                pre_analysis=self._file_output_pre_analysis(artifact_path),
            ),
        )

        with (
            mock.patch("tools.run_plan._is_worktree_clean", return_value=False),
            mock.patch("tools.run_plan.run_pre_analysis", return_value=self._pre_analysis_result(ok=False, tree_modified=True)),
        ):
            code = run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 1
        assert fake_agent.invocations == []
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        step_progress = progress["steps"]["STEP-001"]
        assert step_progress["state"] == "FAILED"
        assert step_progress["failure_reason"]["code"] == "SCOPE_VIOLATION"


# ---------------------------------------------------------------------------
# One-step execution
# ---------------------------------------------------------------------------

class TestOneStep:
    """Verify --one-step executes exactly one step."""

    def test_one_step_executes_and_stops(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step("STEP-001", "First step",
                                     verification_commands=['"python -c \\"print(1)\\"\"']),
            make_implementation_step("STEP-002", "Second step",
                                     verification_commands=['"python -c \\"print(2)\\"\"']),
        )

        fake_agent.enqueue_done("STEP-001")

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True):
            code = run(ctx, one_step=True, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        captured = capsys.readouterr()
        assert "STEP-001" in captured.out

        # Verify progress was saved.
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "DONE"
        assert progress["steps"]["STEP-002"]["state"] == "TODO"

class TestHumanGate:
    """Verify the orchestrator stops at HUMAN_GATE steps."""

    def test_stops_at_human_gate(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ctx = _prepare_run_context(
            tmp_path,
            make_human_gate_step("STEP-001", "Review"),
        )

        fake = FakeAgentAdapter()
        code = run(ctx, adapter=fake, change_detector=FakeChangeDetector({}))

        assert code == 0  # HUMAN_GATE is a clean stop.
        captured = capsys.readouterr()
        assert "HUMAN_GATE" in captured.out


# ---------------------------------------------------------------------------
# STEP-017 — RED tests for --approve-human-gates
# ---------------------------------------------------------------------------

class TestApproveHumanGates:
    """Define HUMAN_GATE auto-approval behavior."""

    @staticmethod
    def _human_gate_with_pre_analysis(
        step_id: str = "STEP-001",
        title: str = "Gate with analysis",
    ) -> str:
        return textwrap.dedent(f"""\
            ### {step_id} — {title}

            ```yaml
            schema_version: 1
            id: {step_id}
            title: {title}
            type: HUMAN_GATE
            review_guidance: Review with diagnostics.
            pre_analysis:
              commands:
                - id: check-tests
                  run: 'python -m pytest tests -q'
                  purpose: Run tests before auto-approving the gate.
                  fail_on_nonzero: true
            ```
        """)

    @staticmethod
    def _pre_analysis_result(
        *,
        outcome: "ScriptOutcome",
        status: str,
        exit_code: int,
        stderr: str = "",
    ) -> "PreAnalysisResult":
        from tools.orchestrator.pre_analysis_runner import PreAnalysisCommandResult, PreAnalysisResult

        return PreAnalysisResult(
            command_results=[
                PreAnalysisCommandResult(
                    command_id="check-tests",
                    command="python -m pytest tests -q",
                    exit_code=exit_code,
                    status=status,
                    duration_seconds=0.1,
                    stdout="ok" if status == "PASS" else "",
                    stderr=stderr,
                    outcome=outcome,
                ),
            ],
            failure_reason=None if status == "PASS" else stderr,
        )

    def test_approve_human_gate_without_pre_analysis_marks_done_and_continues(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        ctx = _prepare_run_context(
            tmp_path,
            make_human_gate_step("STEP-001", "Review"),
            make_implementation_step("STEP-002", "After gate"),
        )
        fake_agent.enqueue_done("STEP-002")

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True):
            code = run(
                ctx,
                approve_human_gates=True,
                adapter=fake_agent,
                change_detector=FakeChangeDetector({}),
            )

        assert code == 0
        assert [request.step_id for request in fake_agent.invocations] == ["STEP-002"]
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "DONE"
        assert progress["steps"]["STEP-002"]["state"] == "DONE"

    def test_approve_human_gate_pre_analysis_pass_marks_done_and_continues(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        from tools.constants import ScriptOutcome

        config = make_default_config(
            automation_dir=str(tmp_path / ".automation"),
            pre_analysis_timeout_seconds=123,
        )
        ctx = _prepare_run_context(
            tmp_path,
            self._human_gate_with_pre_analysis("STEP-001", "Review"),
            make_implementation_step("STEP-002", "After gate"),
            config=config,
        )
        fake_agent.enqueue_done("STEP-002")
        pre_analysis = self._pre_analysis_result(
            outcome=ScriptOutcome.PASS,
            status="PASS",
            exit_code=0,
        )

        with (
            mock.patch("tools.run_plan._is_worktree_clean", return_value=True),
            mock.patch("tools.run_plan.run_pre_analysis", return_value=pre_analysis) as run_pa,
        ):
            code = run(
                ctx,
                approve_human_gates=True,
                adapter=fake_agent,
                change_detector=FakeChangeDetector({}),
            )

        assert code == 0
        run_pa.assert_called_once()
        assert run_pa.call_args.kwargs["timeout_seconds"] == 123
        assert [request.step_id for request in fake_agent.invocations] == ["STEP-002"]
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "DONE"
        assert progress["steps"]["STEP-002"]["state"] == "DONE"

    def test_approve_human_gate_pre_analysis_fail_marks_failed_and_stops(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        from tools.constants import ScriptOutcome

        ctx = _prepare_run_context(
            tmp_path,
            self._human_gate_with_pre_analysis("STEP-001", "Review"),
            make_implementation_step("STEP-002", "After gate"),
        )
        pre_analysis = self._pre_analysis_result(
            outcome=ScriptOutcome.FAIL,
            status="FAIL",
            exit_code=1,
            stderr="tests failed",
        )

        with (
            mock.patch("tools.run_plan._is_worktree_clean", return_value=True),
            mock.patch("tools.run_plan.run_pre_analysis", return_value=pre_analysis),
        ):
            code = run(
                ctx,
                approve_human_gates=True,
                adapter=fake_agent,
                change_detector=FakeChangeDetector({}),
            )

        assert code == 1
        assert fake_agent.invocations == []
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "FAILED"
        assert progress["steps"]["STEP-002"]["state"] == "TODO"

    def test_approve_human_gate_pre_analysis_error_marks_blocked_and_stops(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        from tools.constants import ScriptOutcome

        ctx = _prepare_run_context(
            tmp_path,
            self._human_gate_with_pre_analysis("STEP-001", "Review"),
            make_implementation_step("STEP-002", "After gate"),
        )
        pre_analysis = self._pre_analysis_result(
            outcome=ScriptOutcome.ERROR,
            status="FAIL",
            exit_code=-1,
            stderr="command not found",
        )

        with (
            mock.patch("tools.run_plan._is_worktree_clean", return_value=True),
            mock.patch("tools.run_plan.run_pre_analysis", return_value=pre_analysis),
        ):
            code = run(
                ctx,
                approve_human_gates=True,
                adapter=fake_agent,
                change_detector=FakeChangeDetector({}),
            )

        assert code == 1
        assert fake_agent.invocations == []
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "BLOCKED"
        assert progress["steps"]["STEP-002"]["state"] == "TODO"

    def test_disapprove_human_gate_stops_at_gate_backward_compatibly(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        ctx = _prepare_run_context(
            tmp_path,
            make_human_gate_step("STEP-001", "Review"),
            make_implementation_step("STEP-002", "After gate"),
        )

        code = run(
            ctx,
            approve_human_gates=False,
            adapter=fake_agent,
            change_detector=FakeChangeDetector({}),
        )

        assert code == 0
        assert fake_agent.invocations == []
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "BLOCKED"
        assert progress["steps"]["STEP-002"]["state"] == "TODO"

    def test_approve_human_gate_in_middle_continues_to_later_steps(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step("STEP-001", "Before gate"),
            make_human_gate_step("STEP-002", "Review"),
            make_implementation_step("STEP-003", "After gate"),
        )
        fake_agent.enqueue_done("STEP-001")
        fake_agent.enqueue_done("STEP-003")

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True):
            code = run(
                ctx,
                approve_human_gates=True,
                adapter=fake_agent,
                change_detector=FakeChangeDetector({}),
            )

        assert code == 0
        assert [request.step_id for request in fake_agent.invocations] == ["STEP-001", "STEP-003"]
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "DONE"
        assert progress["steps"]["STEP-002"]["state"] == "DONE"
        assert progress["steps"]["STEP-003"]["state"] == "DONE"


# ---------------------------------------------------------------------------
# STEP-001 — RED tests for new run(ctx) signature
# ---------------------------------------------------------------------------

class TestRunNewSignature:
    """Define the run() contract after prepare_run() owns setup."""

    def test_run_context_completes_valid_one_step_plan(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step("STEP-001", "One step"),
        )
        fake_agent.enqueue_done("STEP-001")

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True):
            code = run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "DONE"

    def test_run_context_one_step_executes_exactly_one_step(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step("STEP-001", "First step"),
            make_implementation_step("STEP-002", "Second step"),
        )
        fake_agent.enqueue_done("STEP-001")

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True):
            code = run(ctx, one_step=True, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        assert [request.step_id for request in fake_agent.invocations] == ["STEP-001"]
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "DONE"
        assert progress["steps"]["STEP-002"]["state"] == "TODO"

    def test_run_context_runs_all_steps_until_completion(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step("STEP-001", "First step"),
            make_implementation_step("STEP-002", "Second step"),
        )
        fake_agent.enqueue_done("STEP-001")
        fake_agent.enqueue_done("STEP-002")

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True):
            code = run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        assert [request.step_id for request in fake_agent.invocations] == ["STEP-001", "STEP-002"]
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "DONE"
        assert progress["steps"]["STEP-002"]["state"] == "DONE"

    def test_run_context_stops_at_human_gate(
        self,
        tmp_path: Path,
    ) -> None:
        ctx = _prepare_run_context(
            tmp_path,
            make_human_gate_step("STEP-001", "Review"),
        )
        fake_agent = FakeAgentAdapter()

        code = run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        assert fake_agent.invocations == []
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "BLOCKED"

    def test_run_context_dirty_worktree_blocks_step(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step("STEP-001", "Dirty-start step"),
        )

        with (
            mock.patch("tools.run_plan._is_worktree_clean", return_value=False),
            mock.patch(
                "tools.run_plan.run_pre_analysis",
                side_effect=AssertionError("pre-analysis should not run for a dirty-start step"),
            ),
        ):
            code = run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 1
        assert fake_agent.invocations == []
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "BLOCKED"
        assert progress["steps"]["STEP-001"]["failure_reason"]["code"] == "DIRTY_WORKTREE"

    def test_run_context_verification_failure_marks_step_failed(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step(
                "STEP-001",
                "Failing verification",
                verification_commands=['"python -c \\"raise SystemExit(1)\\""'],
            ),
        )
        fake_agent.enqueue_done("STEP-001")

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True):
            code = run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 1
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "FAILED"
        assert progress["steps"]["STEP-001"]["failure_reason"]["code"] == "VERIFICATION_FAILED"

    def test_run_context_agent_failed_result_marks_step_failed(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step("STEP-001", "Agent failed step"),
        )
        fake_agent.enqueue_failed("STEP-001", notes="Could not apply requested change")

        with (
            mock.patch("tools.run_plan._is_worktree_clean", return_value=True),
            mock.patch(
                "tools.run_plan.run_verification",
                side_effect=AssertionError("verification should not run after agent FAILED"),
            ),
        ):
            code = run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 1
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        step_progress = progress["steps"]["STEP-001"]
        assert step_progress["state"] == "FAILED"
        assert "Agent returned status FAILED" in step_progress["failure_reason"]["message"]

    def test_run_context_always_calls_git_commit(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        config = make_default_config(
            automation_dir=str(tmp_path / ".automation"),
            git=GitConfig(push_required=False),
        )
        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step("STEP-001", "Commit step"),
            config=config,
        )
        fake_agent.enqueue_done("STEP-001")

        with (
            mock.patch("tools.run_plan._is_worktree_clean", return_value=True),
            mock.patch("tools.run_plan._git_commit", return_value="abc123") as git_commit,
        ):
            code = run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        git_commit.assert_called_once()
        args, kwargs = git_commit.call_args
        assert args[:2] == ("STEP-001", "Commit step")
        assert kwargs.get("push") is False
        assert kwargs.get("config") is config


# ---------------------------------------------------------------------------
# STEP-013 — RED tests for ScriptOutcome ERROR→BLOCKED mapping
# ---------------------------------------------------------------------------

class TestScriptOutcomeErrorBlockedMapping:
    """Define ScriptOutcome state mapping for implementation steps."""

    @staticmethod
    def _pre_analysis_spec() -> dict[str, list[dict[str, object]]]:
        return {
            "commands": [
                {
                    "id": "diagnostic",
                    "run": "python -m pytest tests -q",
                    "purpose": "Run diagnostics before implementation.",
                    "fail_on_nonzero": True,
                },
            ],
        }

    @staticmethod
    def _pre_analysis_result(
        *,
        outcome: "ScriptOutcome",
        status: str,
        exit_code: int,
        stderr: str,
    ) -> "PreAnalysisResult":
        from tools.orchestrator.pre_analysis_runner import PreAnalysisCommandResult, PreAnalysisResult

        return PreAnalysisResult(
            command_results=[
                PreAnalysisCommandResult(
                    command_id="diagnostic",
                    command="python -m pytest tests -q",
                    exit_code=exit_code,
                    status=status,
                    duration_seconds=0.1,
                    stdout="",
                    stderr=stderr,
                    outcome=outcome,
                ),
            ],
            failure_reason=f"diagnostic {status.lower()}",
        )

    @staticmethod
    def _verification_result(
        *,
        outcome: "ScriptOutcome",
        status: str,
        exit_code: int,
        stderr: str,
    ) -> "VerificationResult":
        from tools.orchestrator.verification import VerificationCommandResult, VerificationResult

        return VerificationResult(
            command_results=[
                VerificationCommandResult(
                    command_index=0,
                    command="python -m pytest tests -q",
                    exit_code=exit_code,
                    status=status,
                    duration_seconds=0.1,
                    stdout_tail="",
                    stderr_tail=stderr,
                    log_path=str(Path("verification") / "attempt-1-command-1.log"),
                    outcome=outcome,
                ),
            ],
        )

    def test_implementation_pre_analysis_error_blocks_step(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        from tools.constants import ScriptOutcome

        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step(
                "STEP-001",
                "Pre-analysis script error",
                pre_analysis=self._pre_analysis_spec(),
            ),
        )
        pre_analysis_result = self._pre_analysis_result(
            outcome=ScriptOutcome.ERROR,
            status="FAIL",
            exit_code=-1,
            stderr="command not found",
        )

        with (
            mock.patch("tools.run_plan._is_worktree_clean", return_value=True),
            mock.patch("tools.run_plan.run_pre_analysis", return_value=pre_analysis_result),
        ):
            code = run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 1
        assert fake_agent.invocations == []
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "BLOCKED"

    def test_implementation_pre_analysis_uses_configured_timeout(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        config = make_default_config(
            automation_dir=str(tmp_path / ".automation"),
            pre_analysis_timeout_seconds=123,
        )
        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step(
                "STEP-001",
                "Pre-analysis timeout",
                pre_analysis=self._pre_analysis_spec(),
            ),
            config=config,
        )
        fake_agent.enqueue_done("STEP-001")
        pre_analysis_result = SimpleNamespace(
            ok=True,
            command_results=[],
            failure_reason=None,
            tree_modified=False,
        )

        with (
            mock.patch("tools.run_plan._is_worktree_clean", return_value=True),
            mock.patch("tools.run_plan.run_pre_analysis", return_value=pre_analysis_result) as run_pa,
        ):
            code = run(ctx, one_step=True, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        run_pa.assert_called_once()
        assert run_pa.call_args.kwargs["timeout_seconds"] == 123

    def test_implementation_pre_analysis_fail_marks_step_failed(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        from tools.constants import ScriptOutcome

        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step(
                "STEP-001",
                "Pre-analysis failed",
                pre_analysis=self._pre_analysis_spec(),
            ),
        )
        pre_analysis_result = self._pre_analysis_result(
            outcome=ScriptOutcome.FAIL,
            status="FAIL",
            exit_code=1,
            stderr="tests failed",
        )

        with (
            mock.patch("tools.run_plan._is_worktree_clean", return_value=True),
            mock.patch("tools.run_plan.run_pre_analysis", return_value=pre_analysis_result),
        ):
            code = run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 1
        assert fake_agent.invocations == []
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "FAILED"

    def test_verification_error_blocks_step_without_retry(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        from tools.constants import ScriptOutcome

        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step(
                "STEP-001",
                "Verification script error",
                max_fix_attempts=1,
            ),
        )
        fake_agent.enqueue_done("STEP-001")
        verification_result = self._verification_result(
            outcome=ScriptOutcome.ERROR,
            status="FAIL",
            exit_code=-1,
            stderr="command not found",
        )

        with (
            mock.patch("tools.run_plan._is_worktree_clean", return_value=True),
            mock.patch("tools.run_plan.run_verification", return_value=verification_result),
            mock.patch(
                "tools.run_plan.RetryController",
                side_effect=AssertionError("retry should not be attempted for ScriptOutcome.ERROR"),
            ) as retry_cls,
        ):
            code = run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 1
        retry_cls.assert_not_called()
        assert [request.step_id for request in fake_agent.invocations] == ["STEP-001"]
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "BLOCKED"

    def test_verification_fail_marks_step_failed_after_retry(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        from tools.constants import ScriptOutcome

        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step(
                "STEP-001",
                "Verification failure",
                max_fix_attempts=1,
            ),
        )
        fake_agent.enqueue_done("STEP-001")
        fake_agent.enqueue_done("STEP-001")
        first_failure = self._verification_result(
            outcome=ScriptOutcome.FAIL,
            status="FAIL",
            exit_code=1,
            stderr="tests failed",
        )
        second_failure = self._verification_result(
            outcome=ScriptOutcome.FAIL,
            status="FAIL",
            exit_code=1,
            stderr="tests still failed",
        )

        with (
            mock.patch("tools.run_plan._is_worktree_clean", return_value=True),
            mock.patch("tools.run_plan.run_verification", side_effect=[first_failure, second_failure]) as verify,
        ):
            code = run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 1
        assert verify.call_count == 2
        assert [request.step_id for request in fake_agent.invocations] == ["STEP-001", "STEP-001"]
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "FAILED"
        assert progress["steps"]["STEP-001"]["fix_attempts"] == 1

    def test_failed_retry_result_does_not_rerun_verification(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        from tools.constants import ScriptOutcome

        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step(
                "STEP-001",
                "Failed retry",
                max_fix_attempts=1,
            ),
        )
        fake_agent.enqueue_done("STEP-001")
        fake_agent.enqueue_failed("STEP-001", notes="Fix attempt failed")
        verification_failure = self._verification_result(
            outcome=ScriptOutcome.FAIL,
            status="FAIL",
            exit_code=1,
            stderr="tests failed",
        )

        with (
            mock.patch("tools.run_plan._is_worktree_clean", return_value=True),
            mock.patch("tools.run_plan.run_verification", return_value=verification_failure) as verify,
        ):
            code = run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 1
        assert verify.call_count == 1
        assert [request.step_id for request in fake_agent.invocations] == ["STEP-001", "STEP-001"]
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["state"] == "FAILED"
        assert progress["steps"]["STEP-001"]["fix_attempts"] == 1


# ---------------------------------------------------------------------------
# Resume mode
# ---------------------------------------------------------------------------

class TestResume:
    """Verify --resume continues from existing progress."""

    def test_resume_skips_done_steps(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        plan_text = make_plan(
            make_implementation_step("STEP-001", "First step",
                                     verification_commands=['"python -c \\"print(1)\\"\"']),
            make_implementation_step("STEP-002", "Second step",
                                     verification_commands=['"python -c \\"print(2)\\"\"']),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        # Pre-populate progress: STEP-001 is done.
        automation = tmp_path / ".automation"
        automation.mkdir()
        progress = make_progress(
            plan_file=str(plan_file),
            steps={
                "STEP-001": {"state": "DONE", "completed_at": "2025-01-01T00:00:00Z"},
                "STEP-002": {"state": "TODO"},
            },
        )
        write_progress(automation / "progress.json", progress)

        fake_agent.enqueue_done("STEP-002")

        config = make_default_config(automation_dir=str(automation))
        ctx = prepare_run(str(plan_file), config, resume=True)

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True):
            code = run(ctx, one_step=True, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        captured = capsys.readouterr()
        assert "STEP-002" in captured.out

        updated = json.loads((automation / "progress.json").read_text())
        assert updated["steps"]["STEP-002"]["state"] == "DONE"

    def test_resume_rejects_plan_file_mismatch(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        plan_text = make_plan(
            make_implementation_step("STEP-001", "First step"),
        )
        plan_file = tmp_path / "current-plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        automation = tmp_path / ".automation"
        progress = make_progress(
            plan_file=str(tmp_path / "other-plan.md"),
            steps={"STEP-001": {"state": "TODO"}},
        )
        write_progress(automation / "progress.json", progress)

        config = make_default_config(automation_dir=str(automation))
        with pytest.raises(PrepareError) as exc_info:
            prepare_run(str(plan_file), config, resume=True)

        assert exc_info.value.exit_code == 2
        captured = capsys.readouterr()
        output = str(exc_info.value) + captured.out + captured.err
        assert "plan_file" in output
        assert "resume" in output.lower()

    def test_resume_rejects_removed_step_in_progress(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        plan_text = make_plan(
            make_implementation_step("STEP-001", "Remaining step"),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        automation = tmp_path / ".automation"
        progress = make_progress(
            plan_file=str(plan_file),
            steps={
                "STEP-001": {"state": "TODO"},
                "STEP-002": {"state": "DONE", "completed_at": "2025-01-01T00:00:00Z"},
            },
        )
        write_progress(automation / "progress.json", progress)

        config = make_default_config(automation_dir=str(automation))
        with pytest.raises(PrepareError) as exc_info:
            prepare_run(str(plan_file), config, resume=True)

        assert exc_info.value.exit_code == 2
        captured = capsys.readouterr()
        output = str(exc_info.value) + captured.out + captured.err
        assert "STEP-002" in output
        assert "plan" in output.lower()

    def test_resume_initializes_appended_steps_as_todo(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        plan_text = make_plan(
            make_implementation_step("STEP-001", "Completed step"),
            make_implementation_step("STEP-002", "Appended step"),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        automation = tmp_path / ".automation"
        progress = make_progress(
            plan_file=str(plan_file),
            steps={"STEP-001": {"state": "DONE", "completed_at": "2025-01-01T00:00:00Z"}},
        )
        write_progress(automation / "progress.json", progress)

        config = make_default_config(automation_dir=str(automation))
        prepare_run(str(plan_file), config, resume=True)

        updated = json.loads((automation / "progress.json").read_text())
        assert updated["steps"]["STEP-002"]["state"] == "TODO"
        assert updated["steps"]["STEP-002"]["verification"] is None

    def test_resume_matching_progress_runs_normally(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        plan_text = make_plan(
            make_implementation_step(
                "STEP-001",
                "First step",
                verification_commands=['\'python -c "print(1)"\''],
            ),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        automation = tmp_path / ".automation"
        progress = make_progress(
            plan_file=str(plan_file),
            steps={"STEP-001": {"state": "TODO"}},
        )
        write_progress(automation / "progress.json", progress)
        fake_agent.enqueue_done("STEP-001")

        config = make_default_config(automation_dir=str(automation))
        ctx = prepare_run(str(plan_file), config, resume=True)

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True):
            code = run(ctx, one_step=True, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        assert [request.step_id for request in fake_agent.invocations] == ["STEP-001"]

    def test_resume_invalid_progress_file_returns_2(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        plan_text = make_plan(
            make_implementation_step("STEP-001", "First step"),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        automation = tmp_path / ".automation"
        write_progress(automation / "progress.json", {})

        config = make_default_config(automation_dir=str(automation))
        with pytest.raises(PrepareError) as exc_info:
            prepare_run(str(plan_file), config, resume=True)

        assert exc_info.value.exit_code == 2
        assert "INVALID_PROGRESS_FILE" in str(exc_info.value)

    def test_resume_uses_cli_plan_argument_for_plan_file_check(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        plan_text = make_plan(
            make_implementation_step(
                "STEP-001",
                "Custom plan step",
                verification_commands=['\'python -c "print(1)"\''],
            ),
        )
        plan_file = tmp_path / "custom-plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        automation = tmp_path / ".automation"
        progress = make_progress(
            plan_file=str(plan_file),
            steps={"STEP-001": {"state": "TODO"}},
        )
        write_progress(automation / "progress.json", progress)
        fake_agent.enqueue_done("STEP-001")

        config = make_default_config(automation_dir=str(automation))
        ctx = prepare_run(str(plan_file), config, resume=True)

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True):
            code = run(ctx, one_step=True, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        assert fake_agent.invocations[0].step_id == "STEP-001"


# ---------------------------------------------------------------------------
# Whole-plan mode
# ---------------------------------------------------------------------------

class TestWholePlanMode:
    """Verify whole-plan mode generates a report."""

    def test_whole_plan_generates_report(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        plan_text = make_plan(
            make_implementation_step("STEP-001", "First step",
                                     verification_commands=['"python -c \\"print(1)\\"\"']),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        fake_agent.enqueue_done("STEP-001")

        config = make_default_config(automation_dir=str(tmp_path / ".automation"))
        ctx = prepare_run(str(plan_file), config)

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True):
            code = run(ctx, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        report = tmp_path / ".automation" / "whole-plan-report.md"
        assert report.exists()
        report_text = report.read_text()
        assert "Whole-Plan Report" in report_text


# ---------------------------------------------------------------------------
# Configuration and default adapter wiring
# ---------------------------------------------------------------------------

class TestConfigurationAndAdapterWiring:
    """Verify run_plan uses configuration and creates a production adapter by default."""

    def test_uses_configured_automation_dir_and_default_model(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        plan_text = make_plan(
            make_implementation_step(
                "STEP-001",
                "First step",
                model="default",
                verification_commands=['"python -c \\"print(1)\\""'],
            ),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")
        automation = tmp_path / "custom-automation"
        config = make_default_config(
            default_model="configured-model",
            automation_dir=str(automation),
        )
        fake_agent.enqueue_done("STEP-001")

        ctx = prepare_run(str(plan_file), config)

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True):
            code = run(ctx, one_step=True, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        assert (automation / "progress.json").exists()
        assert fake_agent.invocations[0].model == "configured-model"

    def test_step_model_overrides_config_model(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        plan_text = make_plan(
            make_implementation_step(
                "STEP-001",
                "First step",
                model="step-model",
                verification_commands=['"python -c \\"print(1)\\""'],
            ),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")
        automation = tmp_path / ".automation"
        config = make_default_config(
            default_model="configured-model",
            automation_dir=str(automation),
        )
        fake_agent.enqueue_done("STEP-001")

        ctx = prepare_run(str(plan_file), config)

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True):
            code = run(ctx, one_step=True, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        assert fake_agent.invocations[0].model == "step-model"
        progress = json.loads((automation / "progress.json").read_text(encoding="utf-8"))
        assert progress["steps"]["STEP-001"]["model"] == "step-model"

    def test_creates_default_copilot_adapter_when_none_provided(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        plan_text = make_plan(
            make_implementation_step(
                "STEP-001",
                "First step",
                verification_commands=['"python -c \\"print(1)\\""'],
            ),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")
        automation = tmp_path / ".automation"
        config = make_default_config(automation_dir=str(automation))
        fake_agent.enqueue_done("STEP-001")

        ctx = prepare_run(str(plan_file), config)

        with (
            mock.patch("tools.run_plan.CopilotCliAdapter", return_value=fake_agent) as adapter_cls,
            mock.patch("tools.run_plan._is_worktree_clean", return_value=True),
        ):
            code = run(ctx, one_step=True, change_detector=FakeChangeDetector({}))

        assert code == 0
        adapter_cls.assert_called_once_with(config, automation)
        assert fake_agent.invocations[0].step_id == "STEP-001"

    def test_empty_protected_paths_warns_that_enforcement_is_disabled(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        config = make_default_config(
            automation_dir=str(tmp_path / ".automation"),
            protected_paths=(),
        )
        ctx = _prepare_run_context(
            tmp_path,
            make_implementation_step("STEP-001", "Unprotected run"),
            config=config,
        )
        fake_agent.enqueue_done("STEP-001")

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True):
            code = run(ctx, one_step=True, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        captured = capsys.readouterr()
        assert "protected-file enforcement is disabled" in captured.err



# ---------------------------------------------------------------------------
# STEP-013 — Tests for run refactor (prepare_run, reset_run, reset_current_step)
# ---------------------------------------------------------------------------


class TestPrepareRun:
    """prepare_run() validates plan, creates progress.json, returns context."""

    def test_valid_plan_creates_progress_and_returns_context(self, tmp_path: Path) -> None:
        from tools.run_plan import prepare_run

        plan_text = make_plan(
            make_implementation_step("STEP-001", "First step"),
            make_implementation_step("STEP-002", "Second step"),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        config = make_default_config(automation_dir=str(tmp_path / ".automation"))
        ctx = prepare_run(str(plan_file), config)

        assert isinstance(ctx, RunContext)
        assert (tmp_path / ".automation" / "progress.json").exists()

    def test_invalid_plan_returns_error(self, tmp_path: Path) -> None:
        from tools.run_plan import prepare_run

        plan_file = tmp_path / "plan.md"
        plan_file.write_text("# Empty plan\n", encoding="utf-8")

        config = make_default_config(automation_dir=str(tmp_path / ".automation"))
        with pytest.raises(PrepareError):
            prepare_run(str(plan_file), config)

    def test_resume_mode_loads_existing_progress(self, tmp_path: Path) -> None:
        from tools.run_plan import prepare_run

        plan_text = make_plan(
            make_implementation_step("STEP-001", "First step"),
            make_implementation_step("STEP-002", "Second step"),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        automation = tmp_path / ".automation"
        progress = make_progress(
            steps={
                "STEP-001": {"state": "DONE", "completed_at": "2025-01-01T00:00:00Z"},
                "STEP-002": {"state": "TODO"},
            },
            plan_file=str(plan_file),
        )
        write_progress(automation / "progress.json", progress)

        config = make_default_config(automation_dir=str(automation))
        ctx = prepare_run(str(plan_file), config, resume=True)

        assert isinstance(ctx, RunContext)

    def test_resume_mode_preserves_progress_loader_error(
        self,
        tmp_path: Path,
    ) -> None:
        from tools.run_plan import prepare_run

        plan_text = make_plan(make_implementation_step("STEP-001", "First step"))
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        automation = tmp_path / ".automation"
        write_progress(
            automation / "progress.json",
            make_progress(
                steps={"STEP-001": {"state": "TODO"}},
                plan_file=str(plan_file),
            ),
        )
        config = make_default_config(automation_dir=str(automation))

        error = PrepareError("INVALID_PROGRESS_FILE: precise diagnostic")
        with (
            mock.patch("tools.run_plan._load_resume_progress", side_effect=error),
            pytest.raises(PrepareError, match="precise diagnostic") as exc_info,
        ):
            prepare_run(str(plan_file), config, resume=True)

        assert exc_info.value is error


class TestResetRun:
    """reset_run() resets all steps in progress.json to TODO."""

    def test_existing_progress_resets_all_to_todo(self, tmp_path: Path) -> None:
        from tools.run_plan import reset_run

        automation = tmp_path / ".automation"
        progress = make_progress(
            steps={
                "STEP-001": {"state": "DONE"},
                "STEP-002": {"state": "FAILED"},
            },
        )
        write_progress(automation / "progress.json", progress)

        config = make_default_config(automation_dir=str(automation))
        result = reset_run(config)

        assert result == 0
        updated = json.loads((automation / "progress.json").read_text())
        for step_data in updated["steps"].values():
            assert step_data["state"] == "TODO"

    def test_no_progress_file_returns_error(self, tmp_path: Path) -> None:
        from tools.run_plan import reset_run

        config = make_default_config(automation_dir=str(tmp_path / ".automation"))
        result = reset_run(config)

        assert result != 0


class TestResetCurrentStep:
    """reset_current_step() resets the current step to TODO."""

    def test_failed_step_reset_to_todo(self, tmp_path: Path) -> None:
        from tools.run_plan import reset_current_step

        automation = tmp_path / ".automation"
        progress = make_progress(
            steps={
                "STEP-001": {"state": "DONE"},
                "STEP-002": {"state": "FAILED"},
            },
        )
        write_progress(automation / "progress.json", progress)

        config = make_default_config(automation_dir=str(automation))
        result = reset_current_step(config)

        assert result == 0
        updated = json.loads((automation / "progress.json").read_text())
        assert updated["steps"]["STEP-002"]["state"] == "TODO"

    def test_in_progress_step_reset_to_todo(self, tmp_path: Path) -> None:
        from tools.run_plan import reset_current_step

        automation = tmp_path / ".automation"
        progress = make_progress(
            steps={
                "STEP-001": {"state": "DONE"},
                "STEP-002": {"state": "IN_PROGRESS"},
            },
        )
        write_progress(automation / "progress.json", progress)

        config = make_default_config(automation_dir=str(automation))
        result = reset_current_step(config)

        assert result == 0
        updated = json.loads((automation / "progress.json").read_text())
        assert updated["steps"]["STEP-002"]["state"] == "TODO"

    def test_blocked_step_reset_to_clean_todo(self, tmp_path: Path) -> None:
        from tools.run_plan import reset_current_step

        automation = tmp_path / ".automation"
        progress = make_progress(
            steps={
                "STEP-001": {"state": "DONE"},
                "STEP-002": {
                    "state": "BLOCKED",
                    "failure_reason": {"code": "DIRTY_WORKTREE", "message": "blocked"},
                    "verification": {"status": "FAIL", "attempts": []},
                    "completed_at": "2025-01-01T00:00:00Z",
                    "commit": "abc123",
                    "fix_attempts": 2,
                },
            },
        )
        write_progress(automation / "progress.json", progress)

        config = make_default_config(automation_dir=str(automation))
        result = reset_current_step(config)

        assert result == 0
        updated = json.loads((automation / "progress.json").read_text())
        step_data = updated["steps"]["STEP-002"]
        assert step_data["state"] == "TODO"
        assert step_data["failure_reason"] is None
        assert step_data["verification"] is None
        assert step_data["completed_at"] is None
        assert step_data["commit"] is None
        assert step_data["fix_attempts"] == 0

    def test_all_todo_is_noop(self, tmp_path: Path) -> None:
        from tools.run_plan import reset_current_step

        automation = tmp_path / ".automation"
        progress = make_progress(
            steps={
                "STEP-001": {"state": "TODO"},
                "STEP-002": {"state": "TODO"},
            },
        )
        write_progress(automation / "progress.json", progress)

        config = make_default_config(automation_dir=str(automation))
        result = reset_current_step(config)

        assert result == 0


# ---------------------------------------------------------------------------
# HUMAN_GATE pre-analysis orchestrator tests
# ---------------------------------------------------------------------------


class TestHumanGatePreAnalysis:
    """Verify the orchestrator handles pre-analysis on HUMAN_GATE steps."""

    def _make_gate_plan_with_pre_analysis(self, step_id: str = "STEP-001", title: str = "Gate with analysis") -> str:
        """Build a plan with a single HUMAN_GATE step that has pre_analysis."""
        gate_block = textwrap.dedent(f"""\
            ### {step_id} — {title}

            ```yaml
            schema_version: 1
            id: {step_id}
            title: {title}
            type: HUMAN_GATE
            review_guidance: Review with diagnostics.
            pre_analysis:
              commands:
                - id: check-tests
                  run: 'python -m pytest tests -q'
                  purpose: Run tests before human review
                  fail_on_nonzero: true
            ```
        """)
        return make_plan(gate_block)

    def test_human_gate_pre_analysis_pass_stops_normally(
        self,
        tmp_path: Path,
    ) -> None:
        """HUMAN_GATE with passing pre-analysis → stop normally, logs persisted."""
        from tools.constants import ScriptOutcome
        from tools.orchestrator.pre_analysis_runner import PreAnalysisCommandResult, PreAnalysisResult

        plan_text = self._make_gate_plan_with_pre_analysis()
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        fake = FakeAgentAdapter()
        pa_result = PreAnalysisResult(
            command_results=[
                PreAnalysisCommandResult(
                    command_id="check-tests",
                    command="python -m pytest tests -q",
                    exit_code=0,
                    status="PASS",
                    duration_seconds=1.0,
                    stdout="ok",
                    stderr="",
                    outcome=ScriptOutcome.PASS,
                ),
            ],
        )

        config = make_default_config(
            automation_dir=str(tmp_path / ".automation"),
            pre_analysis_timeout_seconds=123,
        )
        ctx = prepare_run(str(plan_file), config)

        with mock.patch("tools.run_plan.run_pre_analysis", return_value=pa_result) as mock_pa:
            code = run(ctx, adapter=fake, change_detector=FakeChangeDetector({}))

        assert code == 0
        mock_pa.assert_called_once()
        assert mock_pa.call_args.kwargs["timeout_seconds"] == 123

        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        step_prog = progress["steps"]["STEP-001"]
        assert step_prog["state"] == "BLOCKED"
        assert step_prog["pre_analysis"] is not None

    def test_human_gate_pre_analysis_fail_records_failure(
        self,
        tmp_path: Path,
    ) -> None:
        """HUMAN_GATE with failing pre-analysis → stop with failure in progress."""
        from tools.constants import ScriptOutcome
        from tools.orchestrator.pre_analysis_runner import PreAnalysisCommandResult, PreAnalysisResult

        plan_text = self._make_gate_plan_with_pre_analysis()
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        fake = FakeAgentAdapter()
        pa_result = PreAnalysisResult(
            command_results=[
                PreAnalysisCommandResult(
                    command_id="check-tests",
                    command="python -m pytest tests -q",
                    exit_code=1,
                    status="FAIL",
                    duration_seconds=1.0,
                    stdout="",
                    stderr="tests failed",
                    outcome=ScriptOutcome.FAIL,
                ),
            ],
        )

        config = make_default_config(automation_dir=str(tmp_path / ".automation"))
        ctx = prepare_run(str(plan_file), config)

        with mock.patch("tools.run_plan.run_pre_analysis", return_value=pa_result):
            _code = run(ctx, adapter=fake, change_detector=FakeChangeDetector({}))

        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        step_prog = progress["steps"]["STEP-001"]
        assert step_prog["state"] == "FAILED"
        assert step_prog["failure_reason"] is not None

    def test_human_gate_pre_analysis_error_blocks_step(
        self,
        tmp_path: Path,
    ) -> None:
        """HUMAN_GATE with pre-analysis ERROR outcome → step BLOCKED."""
        from tools.constants import ScriptOutcome
        from tools.orchestrator.pre_analysis_runner import PreAnalysisCommandResult, PreAnalysisResult

        plan_text = self._make_gate_plan_with_pre_analysis()
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        fake = FakeAgentAdapter()
        pa_result = PreAnalysisResult(
            command_results=[
                PreAnalysisCommandResult(
                    command_id="check-tests",
                    command="python -m pytest tests -q",
                    exit_code=-1,
                    status="FAIL",
                    duration_seconds=0.1,
                    stdout="",
                    stderr="command not found",
                    outcome=ScriptOutcome.ERROR,
                ),
            ],
        )

        config = make_default_config(automation_dir=str(tmp_path / ".automation"))
        ctx = prepare_run(str(plan_file), config)

        with mock.patch("tools.run_plan.run_pre_analysis", return_value=pa_result):
            _code = run(ctx, adapter=fake, change_detector=FakeChangeDetector({}))

        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        step_prog = progress["steps"]["STEP-001"]
        assert step_prog["state"] == "BLOCKED"

    def test_human_gate_without_pre_analysis_stops_immediately(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """HUMAN_GATE without pre-analysis → stops immediately (backward compatible)."""
        ctx = _prepare_run_context(
            tmp_path,
            make_human_gate_step("STEP-001", "Plain gate"),
        )

        fake = FakeAgentAdapter()
        with mock.patch("tools.run_plan.run_pre_analysis") as mock_pa:
            code = run(ctx, adapter=fake, change_detector=FakeChangeDetector({}))

        assert code == 0
        mock_pa.assert_not_called()
        captured = capsys.readouterr()
        assert "HUMAN_GATE" in captured.out


# ---------------------------------------------------------------------------
# Git timeout passthrough (STEP-031 RED tests)
# ---------------------------------------------------------------------------


class TestGitTimeoutFromConfig:
    """Verify orchestrator passes timeout values from config to Git operations."""

    def test_git_commit_uses_configured_timeout(self, tmp_path: Path) -> None:
        """_git_commit should pass config.git_timeout_seconds to subprocess."""
        from tools.orchestrator.git import git_commit as _git_commit

        plan_text = make_plan(
            make_implementation_step("STEP-001", "Timeout step"),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        config = make_default_config(git_timeout_seconds=45, git_push_timeout_seconds=90)

        with mock.patch("tools.orchestrator.git.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="abc123\n")
            _git_commit("STEP-001", "Timeout step", push=False, config=config)

        assert [call.kwargs["timeout"] for call in mock_run.call_args_list] == [45, 45, 45]

    def test_git_push_uses_configured_push_timeout(self, tmp_path: Path) -> None:
        """_git_commit with push=True should use git_push_timeout_seconds."""
        from tools.orchestrator.git import git_commit as _git_commit

        config = make_default_config(git_timeout_seconds=45, git_push_timeout_seconds=90)

        with mock.patch("tools.orchestrator.git.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="abc123\n")
            _git_commit("STEP-001", "Push step", push=True, config=config)

        # Find the git push call and check its timeout
        push_calls = [
            c for c in mock_run.call_args_list
            if "git" in str(c) and "push" in str(c)
        ]
        assert len(push_calls) == 1
        push_timeout = push_calls[0].kwargs.get("timeout") or push_calls[0][1].get("timeout")
        assert push_timeout == 90


# ---------------------------------------------------------------------------
# Phase 9b — orchestrator assembles structured worker context
# ---------------------------------------------------------------------------


class TestPhase9bOrchestratorContext:
    """The orchestrator passes the per-type system prompt, compiled step prompt,
    and plan context into the invocation request, defaulting the agent."""

    def test_request_carries_system_prompt_step_prompt_and_plan_context(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        plan_text = textwrap.dedent("""\
            # Plan

            ## Project description

            WaterfallRunner drives bounded steps.

            ## Implementation plan

            ### STEP-001 — Do the work

            ```yaml
            schema_version: 1
            id: STEP-001
            title: Do the work
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

            Implement the widget and keep it importable.
        """)
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")
        config = make_default_config(automation_dir=str(tmp_path / ".automation"))
        ctx = prepare_run(str(plan_file), config)
        fake_agent.enqueue_done("STEP-001")

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True):
            code = run(ctx, one_step=True, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        request = fake_agent.invocations[0]
        assert request.agent_name == "default.wfrunner"
        assert request.system_prompt_path.endswith("system_prompt.implementation.md")
        assert "WaterfallRunner drives bounded steps." in request.plan_context
        assert "Implement the widget and keep it importable." in request.step_prompt
        assert not hasattr(request, "prompt_template")

    def test_step_agent_value_is_passed_through(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        plan_text = textwrap.dedent("""\
            # Plan

            ## Implementation plan

            ### STEP-001 — BYO agent

            ```yaml
            schema_version: 1
            id: STEP-001
            title: BYO agent
            type: IMPLEMENTATION
            agent: cppagent
            model: default
            allowed_files:
              - tools/__init__.py
            verification:
              commands:
                - "python -c \\"print(1)\\""
            retry:
              max_fix_attempts: 0
            ```

                        Implement the BYO agent step.
        """)
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")
        config = make_default_config(automation_dir=str(tmp_path / ".automation"))
        ctx = prepare_run(str(plan_file), config)
        fake_agent.enqueue_done("STEP-001")

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True):
            code = run(ctx, one_step=True, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        assert fake_agent.invocations[0].agent_name == "cppagent"

    def test_step_agent_default_sentinel_resolves_to_configured_default(
        self,
        tmp_path: Path,
        fake_agent: FakeAgentAdapter,
    ) -> None:
        plan_text = textwrap.dedent("""\
            # Plan

            ## Implementation plan

            ### STEP-001 — Default agent sentinel

            ```yaml
            schema_version: 1
            id: STEP-001
            title: Default agent sentinel
            type: IMPLEMENTATION
            agent: default
            model: default
            allowed_files:
              - tools/__init__.py
            verification:
              commands:
                - 'python -c "print(1)"'
            retry:
              max_fix_attempts: 0
            ```

            Implement with the configured default agent.
        """)
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")
        config = make_default_config(automation_dir=str(tmp_path / ".automation"))
        ctx = prepare_run(str(plan_file), config)
        fake_agent.enqueue_done("STEP-001")

        with mock.patch("tools.run_plan._is_worktree_clean", return_value=True):
            code = run(ctx, one_step=True, adapter=fake_agent, change_detector=FakeChangeDetector({}))

        assert code == 0
        assert fake_agent.invocations[0].agent_name == "default.wfrunner"
        progress = json.loads((tmp_path / ".automation" / "progress.json").read_text())
        assert progress["steps"]["STEP-001"]["agent"] == "default.wfrunner"

    def test_system_prompt_resolution_falls_back_to_wfrunner_prompts(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from tools.run_plan import _system_prompt_path_for_type

        prompts_dir = tmp_path / ".wfrunner" / "prompts"
        prompts_dir.mkdir(parents=True)
        prompt_path = prompts_dir / "system_prompt.implementation.md"
        prompt_path.write_text("Implement exactly one step.\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        resolved = _system_prompt_path_for_type("IMPLEMENTATION", tmp_path / "custom" / "automation")

        assert resolved == str(prompt_path.resolve())
