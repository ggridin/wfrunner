"""Tests for agent invocation — covers AGENT-001 through AGENT-006.

TDD: These tests are written before the implementation exists.
They define the expected behavior of agent invocation handling
in the orchestrator.
"""

from __future__ import annotations

from pathlib import Path

from tests.fake_agent import FakeAgentAdapter, FakeAgentBehavior, FileAction
from tools.orchestrator.agent_adapter import AgentInvocationRequest, AgentResult
from tools.plan_parser import parse_plan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_steps(plan_text: str):
    """Parse a plan and return the list of parsed steps."""
    result = parse_plan(plan_text)
    assert result.ok, f"Plan parse errors: {result.errors}"
    return result.steps


def _make_request(
    step_id: str = "STEP-001",
    agent_name: str = "default.wfrunner",
    model: str = "default",
    allowed_files: list[str] | None = None,
) -> AgentInvocationRequest:
    """Build a minimal AgentInvocationRequest for testing."""
    return AgentInvocationRequest(
        step_id=step_id,
        agent_name=agent_name,
        model=model,
        system_prompt_path="prompts/system_prompt.implementation.md",
        step_prompt="Do the thing described by this step.",
        plan_context="Project context for the worker.",
        allowed_files=allowed_files or ["tools/__init__.py"],
        verification_commands=["python -c 'print(1)'"],
    )


# ===========================================================================
# AGENT-001: Fake agent returns schema-valid result with status: DONE
#            and modifies allowed file → proceed to verification
# ===========================================================================


class TestAGENT001DoneWithAllowedFileChange:
    """When the agent returns DONE and modifies only allowed files,
    the orchestrator should accept the result and proceed to verification."""

    def test_done_result_is_accepted(self) -> None:
        from tools.orchestrator.agent_invocation import invoke_agent

        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001", notes="All done")
        request = _make_request()

        result = invoke_agent(fake, request)

        assert result.ok is True
        assert result.agent_result is not None
        assert result.agent_result.status == "DONE"
        assert result.agent_result.step_id == "STEP-001"

    def test_done_result_records_invocation(self) -> None:
        from tools.orchestrator.agent_invocation import invoke_agent

        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        request = _make_request()

        invoke_agent(fake, request)

        assert len(fake.invocations) == 1
        assert fake.invocations[0].step_id == "STEP-001"

    def test_done_result_with_file_actions(self, tmp_path: Path) -> None:
        from tools.orchestrator.agent_invocation import invoke_agent

        target = tmp_path / "tools" / "__init__.py"
        target.parent.mkdir(parents=True, exist_ok=True)

        fake = FakeAgentAdapter()
        fake.enqueue_done(
            step_id="STEP-001",
            file_actions=[FileAction(path=str(target), content="# updated")],
        )
        request = _make_request(allowed_files=["tools/__init__.py"])

        result = invoke_agent(fake, request)

        assert result.ok is True
        assert result.agent_result.status == "DONE"


# ===========================================================================
# AGENT-002: Fake agent returns schema-valid result with status: BLOCKED
#            and stop_condition_hit → stop and record block reason
# ===========================================================================


class TestAGENT002BlockedWithStopCondition:
    """When the agent returns BLOCKED with stop_condition_hit set,
    the orchestrator should stop and record the block reason."""

    def test_blocked_result_stops_execution(self) -> None:
        from tools.orchestrator.agent_invocation import invoke_agent

        fake = FakeAgentAdapter()
        fake.enqueue_blocked(
            step_id="STEP-001",
            stop_condition="Ambiguous requirement in spec",
            notes="Cannot proceed without clarification",
        )
        request = _make_request()

        result = invoke_agent(fake, request)

        assert result.ok is False
        assert result.blocked is True
        assert result.agent_result.status == "BLOCKED"
        assert result.agent_result.stop_condition_hit == "Ambiguous requirement in spec"

    def test_blocked_result_records_notes(self) -> None:
        from tools.orchestrator.agent_invocation import invoke_agent

        fake = FakeAgentAdapter()
        fake.enqueue_blocked(
            step_id="STEP-001",
            stop_condition="Missing dependency",
            notes="Library not available",
        )
        request = _make_request()

        result = invoke_agent(fake, request)

        assert result.agent_result.notes == "Library not available"


class TestAGENT002FailedResult:
    """When the agent returns a schema-valid FAILED result,
    the invocation boundary should stop without treating it as BLOCKED
    or schema-invalid."""

    def test_failed_result_stops_execution(self) -> None:
        from tools.orchestrator.agent_invocation import invoke_agent

        fake = FakeAgentAdapter()
        fake.enqueue_failed(step_id="STEP-001", notes="Implementation failed")
        request = _make_request()

        result = invoke_agent(fake, request)

        assert result.ok is False
        assert result.blocked is False
        assert result.invalid_result is False
        assert result.agent_result is not None
        assert result.agent_result.status == "FAILED"
        assert result.failure_reason is not None
        assert "FAILED" in result.failure_reason


# ===========================================================================
# AGENT-003: Fake agent returns malformed JSON or schema-invalid result
#            → stop and record invalid agent result
# ===========================================================================


class TestAGENT003MalformedOrInvalidResult:
    """When the agent returns malformed JSON or a schema-invalid result,
    the orchestrator should stop and record the problem."""

    def test_malformed_json_stops_execution(self) -> None:
        from tools.orchestrator.agent_invocation import invoke_agent

        fake = FakeAgentAdapter()
        fake.enqueue_malformed_json("{not valid json at all}")
        request = _make_request()

        result = invoke_agent(fake, request)

        assert result.ok is False
        assert result.invalid_result is True

    def test_schema_invalid_result_stops_execution(self) -> None:
        from tools.orchestrator.agent_invocation import invoke_agent

        fake = FakeAgentAdapter()
        # Result with missing required fields via raw_json_override.
        fake.enqueue(
            FakeAgentBehavior(
                result=AgentResult(
                    schema_version=1,
                    step_id="STEP-001",
                    status="DONE",
                    raw_json={"schema_version": 1, "status": "DONE"},  # missing step_id
                ),
            )
        )
        request = _make_request()

        result = invoke_agent(fake, request)

        assert result.ok is False
        assert result.invalid_result is True

    def test_extra_fields_in_result_are_rejected(self) -> None:
        from tools.orchestrator.agent_invocation import invoke_agent

        fake = FakeAgentAdapter()
        fake.enqueue(
            FakeAgentBehavior(
                result=AgentResult(
                    schema_version=1,
                    step_id="STEP-001",
                    status="DONE",
                    raw_json={
                        "schema_version": 1,
                        "step_id": "STEP-001",
                        "status": "DONE",
                        "unexpected_field": "surprise",
                    },
                ),
            )
        )
        request = _make_request()

        result = invoke_agent(fake, request)

        assert result.ok is False
        assert result.invalid_result is True


# ===========================================================================
# AGENT-004: Fake agent returns result with mismatched step_id
#            → stop and record invalid agent result
# ===========================================================================


class TestAGENT004MismatchedStepId:
    """When the agent returns a result whose step_id doesn't match
    the request, the orchestrator should stop."""

    def test_mismatched_step_id_stops(self) -> None:
        from tools.orchestrator.agent_invocation import invoke_agent

        fake = FakeAgentAdapter()
        fake.enqueue_mismatched_step(
            "STEP-001",
            returned_step_id="STEP-999",
        )
        request = _make_request(step_id="STEP-001")

        result = invoke_agent(fake, request)

        assert result.ok is False
        assert result.invalid_result is True

    def test_mismatched_step_id_records_reason(self) -> None:
        from tools.orchestrator.agent_invocation import invoke_agent

        fake = FakeAgentAdapter()
        fake.enqueue_mismatched_step(
            "STEP-001",
            returned_step_id="STEP-002",
        )
        request = _make_request(step_id="STEP-001")

        result = invoke_agent(fake, request)

        assert result.ok is False
        assert result.failure_reason is not None
        assert "STEP-002" in result.failure_reason or "mismatch" in result.failure_reason.lower()


# ===========================================================================
# AGENT-005: Agent modifies no files when step expected changes
#            → verification decides outcome
# ===========================================================================


class TestAGENT005NoFilesModified:
    """When the agent returns DONE but modifies no files, the result
    should still be accepted — verification will decide the outcome."""

    def test_done_with_no_file_changes_accepted(self) -> None:
        from tools.orchestrator.agent_invocation import invoke_agent

        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")  # No file_actions
        request = _make_request()

        result = invoke_agent(fake, request)

        # The agent invocation itself should succeed; verification
        # is a separate concern.
        assert result.ok is True
        assert result.agent_result.status == "DONE"

    def test_done_with_no_file_changes_passes_to_verification(self) -> None:
        from tools.orchestrator.agent_invocation import invoke_agent

        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        request = _make_request()

        result = invoke_agent(fake, request)

        # The invocation result should not block verification.
        assert result.ok is True
        assert result.blocked is False


# ===========================================================================
# AGENT-006: Fake agent returns status: BLOCKED without stop_condition_hit
#            → stop and record invalid agent result
# ===========================================================================


class TestAGENT006BlockedWithoutStopCondition:
    """When the agent returns BLOCKED but without stop_condition_hit,
    the result is schema-invalid and the orchestrator should stop."""

    def test_blocked_without_stop_condition_is_invalid(self) -> None:
        from tools.orchestrator.agent_invocation import invoke_agent

        fake = FakeAgentAdapter()
        # Enqueue a BLOCKED result that lacks stop_condition_hit.
        # This violates the agent-result schema's conditional requirement.
        fake.enqueue(
            FakeAgentBehavior(
                result=AgentResult(
                    schema_version=1,
                    step_id="STEP-001",
                    status="BLOCKED",
                    stop_condition_hit=None,  # Missing required field
                ),
            )
        )
        request = _make_request()

        result = invoke_agent(fake, request)

        assert result.ok is False
        assert result.invalid_result is True

    def test_blocked_without_stop_condition_records_reason(self) -> None:
        from tools.orchestrator.agent_invocation import invoke_agent

        fake = FakeAgentAdapter()
        fake.enqueue(
            FakeAgentBehavior(
                result=AgentResult(
                    schema_version=1,
                    step_id="STEP-001",
                    status="BLOCKED",
                    stop_condition_hit=None,
                ),
            )
        )
        request = _make_request()

        result = invoke_agent(fake, request)

        assert result.ok is False
        assert result.failure_reason is not None


# ===========================================================================
# Phase 9b: request carries structured context (system prompt, step prompt,
#           plan context) rather than a template path or source-plan pointer.
# ===========================================================================


class TestPhase9bRequestShape:
    """The invocation request carries the assembled-in-code context fields."""

    def test_request_exposes_structured_context_fields(self) -> None:
        request = _make_request()

        assert request.system_prompt_path == "prompts/system_prompt.implementation.md"
        assert request.step_prompt == "Do the thing described by this step."
        assert request.plan_context == "Project context for the worker."
        assert not hasattr(request, "prompt_template")

    def test_invocation_records_structured_request(self) -> None:
        from tools.orchestrator.agent_invocation import invoke_agent

        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        request = _make_request()

        invoke_agent(fake, request)

        recorded = fake.invocations[0]
        assert recorded.step_prompt == "Do the thing described by this step."
        assert recorded.agent_name == "default.wfrunner"
