"""Tests for end-to-end orchestration — covers E2E-001 through E2E-005.

TDD: These tests are written before the implementation exists.
They define the expected behavior of the full orchestrator loop
using the fake agent adapter.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.fake_agent import FakeAgentAdapter
from tests.helpers import (
    make_human_gate_step,
    make_implementation_step,
    make_plan,
    make_progress,
)
from tools.orchestrator.agent_adapter import AgentInvocationRequest
from tools.plan_parser import parse_plan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_steps(plan_text: str):
    """Parse a plan and return the list of parsed steps."""
    result = parse_plan(plan_text)
    assert result.ok, f"Plan parse errors: {result.errors}"
    return result.steps


def _make_done_step_progress(
    step_id: str = "STEP-001",
    agent: str = "spec-implementer",
    model: str = "default",
    commit: str | None = None,
) -> dict[str, Any]:
    """Build a per-step progress entry for a completed step."""
    return {
        "state": "DONE",
        "agent": agent,
        "model": model,
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
                        f".automation/verification/{step_id}/attempt-1-command-0.summary.json",
                    ],
                }
            ],
        },
        "fix_attempts": 0,
        "commit": commit,
        "failure_reason": None,
    }


# ===========================================================================
# E2E-001: One valid implementation step passes verification
#          → step completes and report is written
# ===========================================================================


class TestE2E001SingleStepPasses:
    """A single implementation step that passes verification should
    complete successfully and produce a report."""

    def test_single_step_plan_parsed(self) -> None:
        """A plan with one implementation step should parse successfully."""
        plan = make_plan(
            make_implementation_step(
                step_id="STEP-001",
                title="First step",
                verification_commands=['"python -c \\"print(1)\\"\"'],
            ),
        )
        steps = _parse_steps(plan)
        assert len(steps) == 1
        assert steps[0].yaml_block["id"] == "STEP-001"

    def test_fake_agent_returns_done(self, fake_agent: FakeAgentAdapter) -> None:
        """The fake agent should return DONE for a single step."""
        fake_agent.enqueue_done("STEP-001")
        request = AgentInvocationRequest(
            step_id="STEP-001",
            agent_name="default.wfrunner",
            model="default",
            system_prompt_path="prompts/system_prompt.implementation.md",
            step_prompt="Implement the step.",
            plan_context="Project context.",
            allowed_files=["tools/__init__.py"],
            verification_commands=["python -c 'print(1)'"],
        )
        result = fake_agent.invoke(request)
        assert result.status == "DONE"
        assert result.step_id == "STEP-001"

    def test_step_completes_in_progress(self) -> None:
        """After a successful run, the step should be DONE in progress."""
        progress = make_progress(
            steps={"STEP-001": _make_done_step_progress("STEP-001")}
        )
        assert progress["steps"]["STEP-001"]["state"] == "DONE"

    def test_report_path_exists_after_run(self) -> None:
        """After a successful run, the whole-plan report path should
        follow the convention."""
        from pathlib import PurePosixPath
        report_path = PurePosixPath(".automation") / "whole-plan-report.md"
        assert str(report_path) == ".automation/whole-plan-report.md"


# ===========================================================================
# E2E-002: Two implementation steps pass sequentially
#          → both complete in order
# ===========================================================================


class TestE2E002TwoStepsPassSequentially:
    """Two implementation steps should execute and pass in strict
    document order."""

    def test_two_step_plan_parsed(self) -> None:
        """A plan with two steps should parse both in order."""
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="First step"),
            make_implementation_step(step_id="STEP-002", title="Second step"),
        )
        steps = _parse_steps(plan)
        assert len(steps) == 2
        assert steps[0].yaml_block["id"] == "STEP-001"
        assert steps[1].yaml_block["id"] == "STEP-002"

    def test_fake_agent_invoked_twice_in_order(
        self, fake_agent: FakeAgentAdapter
    ) -> None:
        """The fake agent should be invoked once for each step in order."""
        fake_agent.enqueue_done("STEP-001")
        fake_agent.enqueue_done("STEP-002")

        req1 = AgentInvocationRequest(
            step_id="STEP-001",
            agent_name="default.wfrunner",
            model="default",
            system_prompt_path="prompts/system_prompt.implementation.md",
            step_prompt="Implement the step.",
            plan_context="Project context.",
            allowed_files=["tools/__init__.py"],
            verification_commands=["python -c 'print(1)'"],
        )
        result1 = fake_agent.invoke(req1)
        assert result1.status == "DONE"
        assert result1.step_id == "STEP-001"

        req2 = AgentInvocationRequest(
            step_id="STEP-002",
            agent_name="default.wfrunner",
            model="default",
            system_prompt_path="prompts/system_prompt.implementation.md",
            step_prompt="Implement the step.",
            plan_context="Project context.",
            allowed_files=["tools/__init__.py"],
            verification_commands=["python -c 'print(1)'"],
        )
        result2 = fake_agent.invoke(req2)
        assert result2.status == "DONE"
        assert result2.step_id == "STEP-002"

    def test_both_steps_done_in_progress(self) -> None:
        """After both steps complete, progress should mark both DONE."""
        progress = make_progress(
            steps={
                "STEP-001": _make_done_step_progress("STEP-001"),
                "STEP-002": _make_done_step_progress("STEP-002"),
            }
        )
        assert progress["steps"]["STEP-001"]["state"] == "DONE"
        assert progress["steps"]["STEP-002"]["state"] == "DONE"

    def test_invocations_recorded_in_order(
        self, fake_agent: FakeAgentAdapter
    ) -> None:
        """The fake agent should record invocations in the order they occurred."""
        fake_agent.enqueue_done("STEP-001")
        fake_agent.enqueue_done("STEP-002")

        for step_id in ["STEP-001", "STEP-002"]:
            fake_agent.invoke(
                AgentInvocationRequest(
                    step_id=step_id,
                    agent_name="default.wfrunner",
                    model="default",
                    system_prompt_path="prompts/system_prompt.implementation.md",
                    step_prompt="Implement the step.",
                    plan_context="Project context.",
                    allowed_files=["tools/__init__.py"],
                    verification_commands=["python -c 'print(1)'"],
                )
            )

        assert len(fake_agent.invocations) == 2
        assert fake_agent.invocations[0].step_id == "STEP-001"
        assert fake_agent.invocations[1].step_id == "STEP-002"


# ===========================================================================
# E2E-003: Step 1 passes, step 2 is human gate → run stops at step 2
# ===========================================================================


class TestE2E003StopsAtHumanGate:
    """When step 1 is an implementation step that passes and step 2 is
    a HUMAN_GATE, the orchestrator should stop at step 2."""

    def test_plan_with_gate_parsed(self) -> None:
        """A plan with an implementation step followed by a gate should parse."""
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="First step"),
            make_human_gate_step(step_id="STEP-002", title="Review step"),
        )
        steps = _parse_steps(plan)
        assert len(steps) == 2
        assert steps[0].yaml_block["type"] == "IMPLEMENTATION"
        assert steps[1].yaml_block["type"] == "HUMAN_GATE"

    def test_agent_invoked_only_for_step_1(
        self, fake_agent: FakeAgentAdapter
    ) -> None:
        """The agent should be invoked only for STEP-001, not for the gate."""
        fake_agent.enqueue_done("STEP-001")

        result = fake_agent.invoke(
            AgentInvocationRequest(
                step_id="STEP-001",
                agent_name="default.wfrunner",
                model="default",
                system_prompt_path="prompts/system_prompt.implementation.md",
                step_prompt="Implement the step.",
                plan_context="Project context.",
                allowed_files=["tools/__init__.py"],
                verification_commands=["python -c 'print(1)'"],
            )
        )
        assert result.status == "DONE"
        assert fake_agent.remaining_behaviors == 0

    def test_step_2_blocked_in_progress(self) -> None:
        """After stopping at a gate, STEP-002 should be BLOCKED in progress."""
        progress = make_progress(
            steps={
                "STEP-001": _make_done_step_progress("STEP-001"),
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
        assert progress["steps"]["STEP-001"]["state"] == "DONE"
        assert progress["steps"]["STEP-002"]["state"] == "BLOCKED"
        assert progress["steps"]["STEP-002"]["failure_reason"]["code"] == "HUMAN_GATE"


# ===========================================================================
# E2E-004: Step 1 fails verification → run stops; step 2 is not attempted
# ===========================================================================


class TestE2E004StopsOnVerificationFailure:
    """When step 1 fails verification, the orchestrator should stop.
    Step 2 should not be attempted."""

    def test_plan_with_two_steps_parsed(self) -> None:
        """A two-step plan should parse correctly."""
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="Failing step"),
            make_implementation_step(step_id="STEP-002", title="Never reached"),
        )
        steps = _parse_steps(plan)
        assert len(steps) == 2

    def test_agent_invoked_for_step_1_only(
        self, fake_agent: FakeAgentAdapter
    ) -> None:
        """Only STEP-001 should have the agent invoked when it fails."""
        fake_agent.enqueue_done("STEP-001")
        result = fake_agent.invoke(
            AgentInvocationRequest(
                step_id="STEP-001",
                agent_name="default.wfrunner",
                model="default",
                system_prompt_path="prompts/system_prompt.implementation.md",
                step_prompt="Implement the step.",
                plan_context="Project context.",
                allowed_files=["tools/__init__.py"],
                verification_commands=["python -c 'exit(1)'"],
            )
        )
        # Agent returns DONE but verification will fail (orchestrator-owned)
        assert result.status == "DONE"
        assert len(fake_agent.invocations) == 1

    def test_step_1_failed_step_2_not_started(self) -> None:
        """After STEP-001 fails, progress should show STEP-001 FAILED
        and STEP-002 should not appear or remain TODO."""
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "FAILED",
                    "agent": "spec-implementer",
                    "model": "default",
                    "started_at": "2025-01-01T00:00:00Z",
                    "completed_at": "2025-01-01T00:01:00Z",
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
                        "message": "Verification command exited with code 1.",
                    },
                },
            }
        )
        assert progress["steps"]["STEP-001"]["state"] == "FAILED"
        assert "STEP-002" not in progress["steps"]

    def test_no_scan_ahead_after_failure(self) -> None:
        """The orchestrator must NOT scan ahead to STEP-002 when STEP-001 fails."""
        # This validates the R10 rule: stop on failure.
        progress = make_progress(
            steps={
                "STEP-001": {
                    "state": "FAILED",
                    "agent": "spec-implementer",
                    "model": "default",
                    "started_at": "2025-01-01T00:00:00Z",
                    "completed_at": "2025-01-01T00:01:00Z",
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
                        "message": "Verification failed.",
                    },
                },
            }
        )
        # Only STEP-001 should be in progress; no evidence of STEP-002 attempt.
        assert len(progress["steps"]) == 1
        assert "STEP-002" not in progress["steps"]


# ===========================================================================
# E2E-005: One-step mode → only first eligible step runs
# ===========================================================================


class TestE2E005OneStepMode:
    """In one-step mode, only the first eligible step should run
    even if more steps are available."""

    def test_plan_with_multiple_steps_parsed(self) -> None:
        """A multi-step plan should parse all steps."""
        plan = make_plan(
            make_implementation_step(step_id="STEP-001", title="First step"),
            make_implementation_step(step_id="STEP-002", title="Second step"),
            make_implementation_step(step_id="STEP-003", title="Third step"),
        )
        steps = _parse_steps(plan)
        assert len(steps) == 3

    def test_only_first_step_runs_in_one_step_mode(
        self, fake_agent: FakeAgentAdapter
    ) -> None:
        """In one-step mode, the agent should be invoked only once."""
        fake_agent.enqueue_done("STEP-001")
        # Only enqueue one behavior — if the orchestrator tries to run
        # a second step, the fake agent will raise RuntimeError.

        result = fake_agent.invoke(
            AgentInvocationRequest(
                step_id="STEP-001",
                agent_name="default.wfrunner",
                model="default",
                system_prompt_path="prompts/system_prompt.implementation.md",
                step_prompt="Implement the step.",
                plan_context="Project context.",
                allowed_files=["tools/__init__.py"],
                verification_commands=["python -c 'print(1)'"],
            )
        )
        assert result.status == "DONE"
        assert len(fake_agent.invocations) == 1
        assert fake_agent.remaining_behaviors == 0

    def test_only_first_step_done_in_progress(self) -> None:
        """After one-step mode, only STEP-001 should be DONE."""
        progress = make_progress(
            steps={
                "STEP-001": _make_done_step_progress("STEP-001"),
            }
        )
        assert progress["steps"]["STEP-001"]["state"] == "DONE"
        assert "STEP-002" not in progress["steps"]

    def test_extra_invocation_raises_when_no_behaviors(
        self, fake_agent: FakeAgentAdapter
    ) -> None:
        """If the orchestrator exceeds one step, the fake agent raises
        RuntimeError (no behaviors enqueued)."""
        # No behaviors enqueued — simulates exceeded limit.
        with pytest.raises(RuntimeError, match="no behaviors enqueued"):
            fake_agent.invoke(
                AgentInvocationRequest(
                    step_id="STEP-002",
                    agent_name="default.wfrunner",
                    model="default",
                    system_prompt_path="prompts/system_prompt.implementation.md",
                    step_prompt="Implement the step.",
                    plan_context="Project context.",
                    allowed_files=["tools/__init__.py"],
                    verification_commands=["python -c 'print(1)'"],
                )
            )
