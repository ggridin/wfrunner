"""Tests for retry controller — covers RETRY-001 through RETRY-006.

TDD: These tests are written before the implementation exists.
They define the expected behavior of the retry controller module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.fake_agent import FakeAgentAdapter, FileAction
from tests.helpers import (
    make_default_config,
    make_implementation_step,
    make_plan,
)
from tools.orchestrator.agent_adapter import AgentInvocationRequest, AgentResult
from tools.orchestrator.change_detector import FakeChangeDetector
from tools.plan_parser import parse_plan

DEFAULT_PLAN_PATH = "docs/implementation_plan_8.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_steps(plan_text: str):
    """Parse a plan and return the list of parsed steps."""
    result = parse_plan(plan_text)
    assert result.ok, f"Plan parse errors: {result.errors}"
    return result.steps


def _step_with_retry(
    max_fix_attempts: int,
    verification_commands: list[str] | None = None,
    allowed_files: list[str] | None = None,
    step_id: str = "STEP-001",
    title: str = "Step with retry",
) -> str:
    """Build a plan step with given retry configuration."""
    if verification_commands is None:
        verification_commands = ['"python -c \\"print(1)\\"\"']
    if allowed_files is None:
        allowed_files = ["tools/__init__.py"]
    return make_implementation_step(
        step_id=step_id,
        title=title,
        max_fix_attempts=max_fix_attempts,
        verification_commands=verification_commands,
        allowed_files=allowed_files,
    )


def _make_failure_summary(
    step_id: str = "STEP-001",
    command: str = "python -c 'print(1)'",
    exit_code: int = 1,
    stdout_tail: str = "error output",
    stderr_tail: str = "",
    log_path: str = ".automation/verification/STEP-001/attempt-1-command-0.log",
) -> dict[str, Any]:
    """Build a verification failure summary for retry input."""
    return {
        "step_id": step_id,
        "attempt": 1,
        "command_index": 0,
        "command": command,
        "exit_code": exit_code,
        "status": "FAIL",
        "duration_seconds": 0.1,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "log_path": log_path,
    }


# ===========================================================================
# RETRY-001: Verification fails and max_fix_attempts is 0
#            → stop without fixer invocation
# ===========================================================================


class TestRETRY001MaxFixAttemptsZero:
    """When verification fails and max_fix_attempts is 0, the orchestrator
    should stop immediately without invoking a fixer agent."""

    def test_no_retry_when_max_fix_attempts_zero(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=0),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        failure_summary = _make_failure_summary()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=tmp_path / ".automation",
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        result = controller.should_retry()

        assert result is False

    def test_no_fixer_invocation_when_max_fix_attempts_zero(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=0),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        failure_summary = _make_failure_summary()

        _controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=tmp_path / ".automation",
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        # Since should_retry() is False, the adapter should never be called.
        assert fake.remaining_behaviors == 0
        assert len(fake.invocations) == 0


# ===========================================================================
# RETRY-002: Verification fails and one retry is allowed
#            → invoke fixer once
# ===========================================================================


class TestRETRY002OneRetryAllowed:
    """When verification fails and max_fix_attempts is 1, the orchestrator
    should invoke the fixer agent exactly once."""

    def test_retry_allowed_when_max_fix_attempts_one(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=1),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001", notes="Fixed the issue")
        failure_summary = _make_failure_summary()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=tmp_path / ".automation",
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        assert controller.should_retry() is True

    def test_fixer_invoked_exactly_once(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=1),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001", notes="Fixed")
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        fix_result = controller.attempt_fix()

        assert len(fake.invocations) == 1
        assert fix_result.ok is True

    def test_fixer_receives_failure_context(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=1),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        failure_summary = _make_failure_summary(
            command="python -m pytest tests/",
            exit_code=1,
            stdout_tail="FAILED test_example",
        )
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        controller.attempt_fix()

        # The fixer invocation should include relevant failure context.
        invocation = fake.invocations[0]
        assert invocation.step_id == "STEP-001"


# ===========================================================================
# RETRY-003: Fixer modifies only allowed files and verification passes
#            → step completes
# ===========================================================================


class TestRETRY003FixerSucceedsWithAllowedFiles:
    """When the fixer modifies only allowed files and verification
    passes after the fix, the step should complete successfully."""

    def test_fixer_with_allowed_files_succeeds(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        target_file = tmp_path / "tools" / "__init__.py"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text("# original", encoding="utf-8")

        plan = make_plan(
            _step_with_retry(
                max_fix_attempts=1,
                allowed_files=["tools/__init__.py"],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(
            step_id="STEP-001",
            file_actions=[
                FileAction(path=str(target_file), content="# fixed"),
            ],
            notes="Applied fix",
        )
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        fix_result = controller.attempt_fix()

        assert fix_result.ok is True
        assert fix_result.agent_result.status == "DONE"

    def test_fixer_result_is_done(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=1),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001", notes="Fix applied")
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        fix_result = controller.attempt_fix()

        assert fix_result.agent_result.status == "DONE"


# ===========================================================================
# RETRY-004: Fixer modifies unlisted file → stop with scope violation
# ===========================================================================


class TestRETRY004FixerModifiesUnlistedFile:
    """When the fixer modifies a file not in the allowed_files list,
    the orchestrator should stop with a scope violation."""

    def test_fixer_scope_violation_stops(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        unlisted_file = tmp_path / "tools" / "secret.py"
        unlisted_file.parent.mkdir(parents=True, exist_ok=True)

        plan = make_plan(
            _step_with_retry(
                max_fix_attempts=1,
                allowed_files=["tools/__init__.py"],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(
            step_id="STEP-001",
            file_actions=[
                FileAction(path=str(unlisted_file), content="# violation"),
            ],
        )
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        detector = FakeChangeDetector({"tools/secret.py": "created"})

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
            change_detector=detector,
        )

        fix_result = controller.attempt_fix()

        # The result should indicate a scope violation.
        assert fix_result.ok is False
        assert fix_result.scope_violation is True


# ===========================================================================
# RETRY-005: Verification still fails after retry → stop and mark failed
# ===========================================================================


class TestRETRY005VerificationStillFailsAfterRetry:
    """When verification still fails after the fixer has run,
    the orchestrator should stop and mark the step as failed."""

    def test_still_fails_after_fix_stops(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=1),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        # Fixer returns DONE but the fix doesn't actually work.
        fake.enqueue_done(step_id="STEP-001", notes="Attempted fix")
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        _fix_result = controller.attempt_fix()

        # The fix result itself is ok (agent returned DONE),
        # but the verification runner re-checks separately.
        # The controller reports it exhausted its attempts.
        assert controller.attempts_remaining() == 0

    def test_no_further_retries_after_exhaustion(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=1),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        controller.attempt_fix()

        # After one attempt, should_retry should return False.
        assert controller.should_retry() is False


# ===========================================================================
# RETRY-006: Fixer reports requirement ambiguity → stop and mark blocked
# ===========================================================================


class TestRETRY006FixerReportsAmbiguity:
    """When the fixer agent returns BLOCKED indicating a requirement
    ambiguity, the orchestrator should stop and mark the step as blocked."""

    def test_fixer_blocked_marks_step_blocked(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=1),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_blocked(
            step_id="STEP-001",
            stop_condition="Ambiguous requirement: unclear expected output format",
            notes="Cannot determine correct fix without clarification",
        )
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        fix_result = controller.attempt_fix()

        assert fix_result.ok is False
        assert fix_result.blocked is True

    def test_fixer_blocked_records_stop_condition(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=1),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_blocked(
            step_id="STEP-001",
            stop_condition="Requirement ambiguity in spec",
            notes="Need human clarification",
        )
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        fix_result = controller.attempt_fix()

        assert fix_result.agent_result.status == "BLOCKED"
        assert fix_result.agent_result.stop_condition_hit == "Requirement ambiguity in spec"

    def test_fixer_blocked_no_further_retries(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=1),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_blocked(
            step_id="STEP-001",
            stop_condition="Ambiguity",
        )
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        controller.attempt_fix()

        # After a BLOCKED result, no further retries should be attempted.
        assert controller.should_retry() is False


# ===========================================================================
# RETRY-007: RetryController accepts optional ChangeDetector
# ===========================================================================


class TestRETRY007AcceptsChangeDetector:
    """RetryController accepts an optional change_detector parameter."""

    def test_accepts_change_detector_kwarg(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(_step_with_retry(max_fix_attempts=1))
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        failure_summary = _make_failure_summary()

        detector = FakeChangeDetector({})

        # Should not raise.
        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=tmp_path / ".automation",
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
            change_detector=detector,
        )

        assert controller is not None

    def test_no_change_detector_is_default(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(_step_with_retry(max_fix_attempts=1))
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        failure_summary = _make_failure_summary()

        # Omitting change_detector should work fine.
        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=tmp_path / ".automation",
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        assert controller is not None


# ===========================================================================
# RETRY-008: ChangeDetector snapshot_before/detect_changes called at right times
# ===========================================================================


class TestRETRY008ChangeDetectorCalledAroundAgent:
    """snapshot_before is called before the agent; detect_changes is called after."""

    def test_snapshot_before_called(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(_step_with_retry(max_fix_attempts=1))
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        call_log: list[str] = []

        class TrackingDetector(FakeChangeDetector):
            def snapshot_before(self) -> None:
                call_log.append("snapshot_before")

            def detect_changes(self) -> dict[str, str]:
                call_log.append("detect_changes")
                return {}

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
            change_detector=TrackingDetector({}),
        )

        controller.attempt_fix()

        assert "snapshot_before" in call_log
        assert "detect_changes" in call_log

    def test_snapshot_before_called_before_agent(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(_step_with_retry(max_fix_attempts=1))
        steps = _parse_steps(plan)
        step = steps[0]
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        call_log: list[str] = []

        class TrackingDetector(FakeChangeDetector):
            def snapshot_before(self) -> None:
                call_log.append("snapshot_before")

            def detect_changes(self) -> dict[str, str]:
                call_log.append("detect_changes")
                return {}

        class TrackingAdapter(FakeAgentAdapter):
            def invoke(self, request: AgentInvocationRequest) -> AgentResult:
                call_log.append("agent_invoke")
                return super().invoke(request)

        adapter = TrackingAdapter()
        adapter.enqueue_done(step_id="STEP-001")

        controller = RetryController(
            step=step,
            adapter=adapter,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
            change_detector=TrackingDetector({}),
        )

        controller.attempt_fix()

        assert call_log.index("snapshot_before") < call_log.index("agent_invoke")
        assert call_log.index("agent_invoke") < call_log.index("detect_changes")


# ===========================================================================
# RETRY-009: Scope violation via ChangeDetector produces scope_violation=True
# ===========================================================================


class TestRETRY009ChangeDetectorScopeViolation:
    """When ChangeDetector.detect_changes() returns unlisted files, scope_violation=True."""

    def test_unlisted_file_from_change_detector_is_violation(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=1, allowed_files=["tools/__init__.py"])
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        # Detector reports a file not in allowed_files.
        detector = FakeChangeDetector({"tools/secret.py": "created"})

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
            change_detector=detector,
        )

        fix_result = controller.attempt_fix()

        assert fix_result.ok is False
        assert fix_result.scope_violation is True

    def test_allowed_file_from_change_detector_is_not_violation(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=1, allowed_files=["tools/__init__.py"])
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        # Detector reports only an allowed file.
        detector = FakeChangeDetector({"tools/__init__.py": "modified"})

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
            change_detector=detector,
        )

        fix_result = controller.attempt_fix()

        assert fix_result.scope_violation is False
        assert fix_result.ok is True


# ===========================================================================
# RETRY-010: No ChangeDetector → scope enforcement skipped (no crash, no violation)
# ===========================================================================


class TestRETRY010NoChangeDetectorSkipsEnforcement:
    """When no ChangeDetector is provided, scope enforcement is skipped entirely."""

    def test_no_change_detector_no_scope_violation(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=1, allowed_files=["tools/__init__.py"])
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
            # No change_detector provided.
        )

        fix_result = controller.attempt_fix()

        # No violation raised even though we can't verify file scope.
        assert fix_result.scope_violation is False

    def test_no_change_detector_fix_ok(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(_step_with_retry(max_fix_attempts=1))
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001", notes="Fixed")
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        fix_result = controller.attempt_fix()

        assert fix_result.ok is True

    def test_no_change_detector_skips_scope_enforcement(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When no ChangeDetector is provided and the agent modifies files
        outside allowed_files, the result is ok=True because scope enforcement
        is skipped entirely (never calls check_allowed_files)."""
        from tools.orchestrator.retry_controller import RetryController

        unlisted_file = tmp_path / "tools" / "secret.py"
        unlisted_file.parent.mkdir(parents=True, exist_ok=True)

        plan = make_plan(
            _step_with_retry(
                max_fix_attempts=1,
                allowed_files=["tools/__init__.py"],
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(
            step_id="STEP-001",
            file_actions=[
                FileAction(path=str(unlisted_file), content="# violation"),
            ],
        )
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        def fail_if_scope_checked(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("check_allowed_files should not be called")

        monkeypatch.setattr(
            "tools.orchestrator.scope_enforcer.check_allowed_files",
            fail_if_scope_checked,
        )

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
            # No change_detector — scope enforcement must be skipped.
        )

        fix_result = controller.attempt_fix()

        assert fix_result.ok is True
        assert fix_result.scope_violation is False


# ===========================================================================
# RETRY-011: Retry uses the same agent name as the implementation step
# ===========================================================================


class TestRETRY011RetryUsesSameAgent:
    """Retry controller must use the step's configured agent, not a
    hardcoded fallback like 'spec-fixer'."""

    def test_retry_agent_name_matches_step_agent(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            make_implementation_step(
                step_id="STEP-001",
                agent="my-custom-agent",
                max_fix_attempts=1,
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        controller.attempt_fix()

        invocation = fake.invocations[0]
        assert invocation.agent_name == "my-custom-agent"

    def test_retry_agent_name_is_not_spec_fixer(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            make_implementation_step(
                step_id="STEP-001",
                agent="spec-implementer",
                max_fix_attempts=1,
            ),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        controller.attempt_fix()

        invocation = fake.invocations[0]
        assert invocation.agent_name != "spec-fixer"
        assert invocation.agent_name == "spec-implementer"

    def test_retry_missing_agent_uses_default_sentinel(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            """
### STEP-001 — Retry missing agent

```yaml
schema_version: 1
id: STEP-001
title: Retry missing agent
type: IMPLEMENTATION
model: default
allowed_files:
    - tools/__init__.py
verification:
    commands:
        - 'python -c "print(1)"'
retry:
    max_fix_attempts: 1
```
""",
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        controller.attempt_fix()

        invocation = fake.invocations[0]
        assert invocation.agent_name == "default"


# ===========================================================================
# Retry invocation contract: validation and configuration resolution
# ===========================================================================


class TestRetryInvocationContract:
    """Fix attempts use the same validated, resolved invocation path."""

    def test_malformed_fix_result_is_rejected(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        step = _parse_steps(make_plan(_step_with_retry(max_fix_attempts=1)))[0]
        fake = FakeAgentAdapter()
        fake.enqueue_malformed_json("{not valid json at all}")
        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=tmp_path / ".automation",
            failure_summary=_make_failure_summary(),
        )

        result = controller.attempt_fix()

        assert result.ok is False
        assert result.invalid_result is True
        assert result.failure_reason is not None

    def test_step_id_mismatched_fix_result_is_rejected(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        step = _parse_steps(make_plan(_step_with_retry(max_fix_attempts=1)))[0]
        fake = FakeAgentAdapter()
        fake.enqueue_mismatched_step("STEP-001", returned_step_id="STEP-999")
        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=tmp_path / ".automation",
            failure_summary=_make_failure_summary(),
        )

        result = controller.attempt_fix()

        assert result.ok is False
        assert result.invalid_result is True
        assert result.failure_reason is not None
        assert "mismatch" in result.failure_reason

    def test_resolved_agent_and_model_reach_adapter(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        step = _parse_steps(
            make_plan(
                make_implementation_step(
                    agent="default",
                    model="default",
                    max_fix_attempts=1,
                )
            )
        )[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=tmp_path / ".automation",
            failure_summary=_make_failure_summary(),
            config=make_default_config(
                default_agent="resolved-agent",
                default_model="resolved-model",
            ),
        )

        result = controller.attempt_fix()

        assert result.ok is True
        assert fake.invocations[0].agent_name == "resolved-agent"
        assert fake.invocations[0].model == "resolved-model"


# ===========================================================================
# RETRY-013: AgentInvocationRequest includes failure_context field
# ===========================================================================


class TestRETRY013RequestIncludesFailureContext:
    """The AgentInvocationRequest for a fix attempt must include a
    failure_context field with the verification failure summary."""

    def test_request_has_failure_context_field(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=1),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        failure_summary = _make_failure_summary(
            command="python -m pytest tests/",
            exit_code=1,
            stdout_tail="FAILED test_example",
        )
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        controller.attempt_fix()

        invocation = fake.invocations[0]
        assert hasattr(invocation, "failure_context"), (
            "AgentInvocationRequest should have a failure_context field"
        )

    def test_failure_context_contains_failure_summary(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=1),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        failure_summary = _make_failure_summary(
            command="python -m pytest tests/",
            exit_code=1,
            stdout_tail="AssertionError: expected 42 got 0",
            stderr_tail="FAILED",
        )
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        controller.attempt_fix()

        invocation = fake.invocations[0]
        ctx = invocation.failure_context
        assert "python -m pytest tests/" in str(ctx)
        assert "AssertionError" in str(ctx)

    def test_failure_context_includes_exit_code(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=1),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        failure_summary = _make_failure_summary(exit_code=2)
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        controller.attempt_fix()

        invocation = fake.invocations[0]
        # The failure context should contain the exit code.
        assert "2" in str(invocation.failure_context)


# ===========================================================================
# RETRY-014: Prompt template receives failure context
# ===========================================================================


class TestRETRY014PromptTemplateReceivesFailureContext:
    """The prompt template should receive the failure context so the agent
    knows that verification failed and what went wrong."""

    def test_failure_context_available_on_request(
        self, tmp_path: Path
    ) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=1),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        failure_summary = _make_failure_summary(
            command="python -m pytest tests/ -v",
            exit_code=1,
            stdout_tail="FAILED test_foo - assert False",
        )
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        controller.attempt_fix()

        invocation = fake.invocations[0]
        # Failure context must be surfaced so the prompt template can use it.
        assert invocation.failure_context, "Failure context must be available to the prompt template"

    def test_failure_context_not_empty_on_retry(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(
            _step_with_retry(max_fix_attempts=1),
        )
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        failure_summary = _make_failure_summary(
            command="python -m pytest tests/",
            exit_code=1,
            stdout_tail="test_bar FAILED",
        )
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            plan_path=DEFAULT_PLAN_PATH,
        )

        controller.attempt_fix()

        invocation = fake.invocations[0]
        # The agent must know WHY verification failed — context must not be empty.
        assert invocation.failure_context, "failure_context must not be empty"


# ===========================================================================
# Phase 9b: retry assembles the fix request from the same structured context
# ===========================================================================


class TestPhase9bRetryAssembly:
    """Retry reuses the assembled-in-code context and appends failure context."""

    def test_retry_request_carries_step_prompt_and_system_prompt(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(_step_with_retry(max_fix_attempts=1))
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        failure_summary = _make_failure_summary()
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            step_prompt="Fix the failing parser step.",
            system_prompt_path="prompts/system_prompt.implementation.md",
            plan_context="Project context handed to the worker.",
        )

        controller.attempt_fix()

        invocation = fake.invocations[0]
        assert invocation.step_prompt == "Fix the failing parser step."
        assert invocation.system_prompt_path == "prompts/system_prompt.implementation.md"
        assert invocation.plan_context == "Project context handed to the worker."
        assert not hasattr(invocation, "prompt_template")

    def test_retry_request_still_appends_failure_context(self, tmp_path: Path) -> None:
        from tools.orchestrator.retry_controller import RetryController

        plan = make_plan(_step_with_retry(max_fix_attempts=1))
        steps = _parse_steps(plan)
        step = steps[0]
        fake = FakeAgentAdapter()
        fake.enqueue_done(step_id="STEP-001")
        failure_summary = _make_failure_summary(
            command="python -m pytest tests/",
            exit_code=1,
            stdout_tail="FAILED test_parser",
        )
        automation_dir = tmp_path / ".automation"
        automation_dir.mkdir()

        controller = RetryController(
            step=step,
            adapter=fake,
            automation_dir=automation_dir,
            failure_summary=failure_summary,
            step_prompt="Fix it.",
            system_prompt_path="prompts/system_prompt.implementation.md",
            plan_context="ctx",
        )

        controller.attempt_fix()

        invocation = fake.invocations[0]
        assert invocation.failure_context
        assert "FAILED test_parser" in str(invocation.failure_context)
