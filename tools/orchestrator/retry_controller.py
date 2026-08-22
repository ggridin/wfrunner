"""Retry controller — manages bounded retry after verification failure."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.config import WaterfallRunnerConfig
from tools.constants import (
    AGENT_DEFAULT,
    FIELD_AGENT,
    FIELD_ALLOWED_FILES,
    FIELD_COMMANDS,
    FIELD_ID,
    FIELD_MAX_FIX_ATTEMPTS,
    FIELD_MODEL,
    FIELD_RETRY,
    FIELD_VERIFICATION,
    MODEL_DEFAULT,
)
from tools.orchestrator.agent_adapter import AgentAdapter, AgentInvocationRequest, AgentResult
from tools.orchestrator.agent_invocation import invoke_agent
from tools.orchestrator.change_detector import ChangeDetector
from tools.plan_parser import ParsedStep


@dataclass
class FixResult:
    """Result of a single fix attempt."""

    agent_result: AgentResult
    ok: bool = True
    blocked: bool = False
    failed: bool = False
    invalid_result: bool = False
    scope_violation: bool = False
    failure_reason: str | None = None


class RetryController:
    """Controls bounded retry after verification failure.

    The controller tracks the number of fix attempts used and whether
    further retries are allowed.
    """

    def __init__(
        self,
        *,
        step: ParsedStep,
        adapter: AgentAdapter,
        automation_dir: Path,
        failure_summary: dict[str, Any],
        step_prompt: str = "",
        system_prompt_path: str = "",
        plan_context: str = "",
        plan_path: str | None = None,
        change_detector: ChangeDetector | None = None,
        config: WaterfallRunnerConfig | None = None,
    ) -> None:
        self._step = step
        self._adapter = adapter
        self._automation_dir = automation_dir
        self._working_dir = automation_dir.parent
        self._failure_summary = failure_summary
        self._change_detector = change_detector
        self._step_prompt = step_prompt
        self._system_prompt_path = system_prompt_path
        self._plan_context = plan_context
        self._config = config or getattr(adapter, "config", None)
        self._max_fix_attempts = step.yaml_block.get(FIELD_RETRY, {}).get(FIELD_MAX_FIX_ATTEMPTS, 0)
        self._attempts_used = 0
        self._blocked = False

    def should_retry(self) -> bool:
        """Return True if a fix attempt is allowed."""
        if self._blocked:
            return False
        return self._attempts_used < self._max_fix_attempts

    def attempts_remaining(self) -> int:
        """Return the number of fix attempts remaining."""
        remaining = self._max_fix_attempts - self._attempts_used
        return max(0, remaining)

    def attempt_fix(self) -> FixResult:
        """Invoke the fixer agent for one fix attempt.

        Returns:
            A FixResult describing the outcome.
        """
        self._attempts_used += 1

        step_yaml = self._step.yaml_block
        agent_name = step_yaml.get(FIELD_AGENT, AGENT_DEFAULT)
        model = step_yaml.get(FIELD_MODEL, MODEL_DEFAULT)
        if self._config is not None:
            agent_name = self._config.resolve_agent(agent_name)
            model = self._config.resolve_model(model)
        request = AgentInvocationRequest(
            step_id=step_yaml[FIELD_ID],
            agent_name=agent_name,
            model=model,
            system_prompt_path=self._system_prompt_path,
            step_prompt=self._step_prompt,
            plan_context=self._plan_context,
            allowed_files=step_yaml.get(FIELD_ALLOWED_FILES, []),
            verification_commands=step_yaml.get(FIELD_VERIFICATION, {}).get(FIELD_COMMANDS, []),
            failure_context=self._failure_summary if self._failure_summary else None,
            title=self._step.heading_title,
        )

        # Snapshot files before agent invocation.
        if self._change_detector is not None:
            self._change_detector.snapshot_before()

        invocation_result = invoke_agent(self._adapter, request)
        agent_result = invocation_result.agent_result
        if agent_result is None:
            raise RuntimeError("Agent invocation completed without an agent result.")

        if not invocation_result.ok:
            if invocation_result.blocked:
                self._blocked = True
            return FixResult(
                agent_result=agent_result,
                ok=False,
                blocked=invocation_result.blocked,
                failed=invocation_result.failed,
                invalid_result=invocation_result.invalid_result,
                failure_reason=invocation_result.failure_reason,
            )

        # Detect scope violations.
        if self._change_detector is None:
            # No detector — skip scope enforcement entirely.
            return FixResult(agent_result=agent_result, ok=True)

        changed = self._change_detector.detect_changes()
        allowed_set = set(step_yaml.get(FIELD_ALLOWED_FILES, []))

        from tools.orchestrator.scope_enforcer import check_allowed_files

        violations = check_allowed_files(list(allowed_set), changed)
        if violations:
            return FixResult(
                agent_result=agent_result,
                ok=False,
                scope_violation=True,
            )

        return FixResult(agent_result=agent_result, ok=True)
