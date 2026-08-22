"""Step-type handlers for executing runnable plan steps."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
import subprocess
from pathlib import Path
from typing import Any, Protocol

from tools.config import WaterfallRunnerConfig
from tools.constants import (
    AGENT_DEFAULT,
    AGENT_STATUS_FAILED,
    FIELD_AGENT,
    FIELD_ALLOWED_FILES,
    FIELD_COMMANDS,
    FIELD_ID,
    FIELD_MODEL,
    FIELD_PRE_ANALYSIS,
    FIELD_TYPE,
    FIELD_VERIFICATION,
    FR_CODE,
    FR_MESSAGE,
    FAILURE_AGENT_BLOCKED,
    FAILURE_DIRTY_WORKTREE,
    FAILURE_INVALID_AGENT_RESULT,
    FAILURE_PRE_ANALYSIS_FAILED,
    FAILURE_SCOPE_VIOLATION,
    FAILURE_VERIFICATION_FAILED,
    MODEL_DEFAULT,
    PROGRESS_FIELD_COMMIT,
    PROGRESS_FIELD_FIX_ATTEMPTS,
    PROGRESS_FIELD_PRE_ANALYSIS,
    PROGRESS_FIELD_VERIFICATION,
    ScriptOutcome,
    STEP_TYPE_ANALYSIS,
    STEP_TYPE_IMPLEMENTATION,
    VERIFY_FAIL,
    VERIFY_PASS,
)
from tools.orchestrator.agent_adapter import AgentAdapter, AgentInvocationRequest
from tools.orchestrator.agent_invocation import invoke_agent
from tools.orchestrator.change_detector import ChangeDetector
from tools.orchestrator.outcomes import StepOutcome
from tools.orchestrator.pre_analysis_runner import run_pre_analysis
from tools.orchestrator.retry_controller import RetryController
from tools.orchestrator.scope_enforcer import check_allowed_files
from tools.orchestrator.verification import VerificationResult, run_verification
from tools.plan_parser import ParsedStep


class _ScriptCommandResult(Protocol):
    outcome: ScriptOutcome


@dataclass(frozen=True)
class StepExecutionResult:
    """Structured result returned by a step-type handler."""

    outcome: StepOutcome | None = None
    failure_reason: dict[str, str] | None = None
    agent: str | None = None
    verification_status: str | None = None
    extra_fields: dict[str, Any] = field(default_factory=dict)
    message: str | None = None
    message_is_error: bool = False

    @property
    def completed(self) -> bool:
        return self.outcome is None


@dataclass(frozen=True)
class StepExecutionContext:
    """Dependencies and run data required to execute one plan step."""

    step: ParsedStep
    adapter: AgentAdapter
    automation_dir: Path
    config: WaterfallRunnerConfig
    step_prompt: str
    plan_context: str
    change_detector: ChangeDetector | None
    no_scope_enforcement: bool
    push_required: bool
    is_worktree_clean: Callable[[WaterfallRunnerConfig], bool]
    git_commit: Callable[..., str | None]
    pre_analysis_runner: Callable[..., Any] = run_pre_analysis
    verification_runner: Callable[..., VerificationResult] = run_verification


StepHandler = Callable[[StepExecutionContext], StepExecutionResult]


def _has_script_error(command_results: Iterable[_ScriptCommandResult]) -> bool:
    return any(result.outcome == ScriptOutcome.ERROR for result in command_results)


def _pre_analysis_summary(result: Any) -> dict[str, Any]:
    return {
        "status": VERIFY_PASS if result.ok else VERIFY_FAIL,
        "commands": [
            {
                "command_id": command_result.command_id,
                "status": VERIFY_FAIL if command_result.status == VERIFY_FAIL else VERIFY_PASS,
                "summary_path": command_result.summary_path,
            }
            for command_result in result.command_results
        ],
    }


def _verification_attempt_status(result: VerificationResult) -> str:
    if result.ok:
        return VERIFY_PASS
    for command_result in result.command_results:
        if command_result.status != VERIFY_PASS:
            return command_result.status
    return VERIFY_FAIL


def _verification_summary(status: str, attempts: list[VerificationResult]) -> dict[str, Any]:
    return {
        "status": status,
        "attempts": [
            {
                "attempt": attempt_number,
                "status": _verification_attempt_status(attempt_result),
                "command_summaries": [
                    str(Path(command_result.log_path).with_suffix(".summary.json"))
                    for command_result in attempt_result.command_results
                ],
            }
            for attempt_number, attempt_result in enumerate(attempts, start=1)
        ],
    }


_SYSTEM_PROMPT_IMPLEMENTATION = "system_prompt.implementation.md"
_SYSTEM_PROMPT_ANALYSIS = "system_prompt.analysis.md"


def system_prompt_path_for_type(step_type: str | None, automation_dir: Path) -> str:
    """Return the scaffolded per-type system prompt path for a step type."""
    prompt_name = (
        _SYSTEM_PROMPT_ANALYSIS
        if step_type == STEP_TYPE_ANALYSIS
        else _SYSTEM_PROMPT_IMPLEMENTATION
    )
    candidates = [
        automation_dir.parent / "prompts" / prompt_name,
        Path(".wfrunner") / "prompts" / prompt_name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate.resolve())
    return str(candidates[0].resolve())


def _analysis_git_snapshot(config: WaterfallRunnerConfig) -> str | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            capture_output=True,
            text=True,
            timeout=config.git_timeout_seconds,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _analysis_changed(
    context: StepExecutionContext,
    *,
    before_git_snapshot: str | None,
    clean_fallback: bool,
) -> bool:
    if context.change_detector is not None:
        return bool(context.change_detector.detect_changes())
    if before_git_snapshot is not None:
        after_git_snapshot = _analysis_git_snapshot(context.config)
        return after_git_snapshot is None or after_git_snapshot != before_git_snapshot
    if clean_fallback:
        return not context.is_worktree_clean(context.config)
    return True


def _invoke(
    context: StepExecutionContext,
    request: AgentInvocationRequest,
    *,
    analysis: bool = False,
) -> StepExecutionResult | None:
    try:
        invocation_result = invoke_agent(context.adapter, request)
    except FileNotFoundError as exc:
        return StepExecutionResult(
            outcome=StepOutcome.AGENT_BLOCKED,
            failure_reason={
                FR_CODE: FAILURE_AGENT_BLOCKED,
                FR_MESSAGE: f"Agent command not found: {exc.filename}",
            },
            agent=request.agent_name,
            message=f"Agent command not found: {exc.filename}",
            message_is_error=True,
        )

    if invocation_result.ok:
        return None
    if invocation_result.blocked:
        return StepExecutionResult(
            outcome=StepOutcome.AGENT_BLOCKED,
            failure_reason={
                FR_CODE: FAILURE_AGENT_BLOCKED,
                FR_MESSAGE: (
                    invocation_result.agent_result.stop_condition_hit
                    if invocation_result.agent_result
                    else "Agent blocked."
                ),
            },
            agent=request.agent_name,
            message=f"{'Analysis agent' if analysis else 'Agent'} blocked at {request.step_id}.",
            message_is_error=True,
        )

    outcome = (
        StepOutcome.AGENT_FAILED
        if invocation_result.failed or analysis
        else StepOutcome.INVALID_AGENT_RESULT
    )
    return StepExecutionResult(
        outcome=outcome,
        failure_reason={
            FR_CODE: FAILURE_INVALID_AGENT_RESULT,
            FR_MESSAGE: invocation_result.failure_reason or "Agent failed.",
        },
        agent=request.agent_name,
        message=f"{'Analysis agent' if analysis else 'Agent'} failed at {request.step_id}.",
        message_is_error=True,
    )


def execute_analysis_step(context: StepExecutionContext) -> StepExecutionResult:
    """Execute an ANALYSIS step and enforce its read-only contract."""
    step = context.step
    step_yaml = step.yaml_block
    step_id = step_yaml[FIELD_ID]
    before_git_snapshot: str | None = None
    clean_fallback = False

    if not context.no_scope_enforcement:
        if context.change_detector is not None:
            context.change_detector.snapshot_before()
        else:
            before_git_snapshot = _analysis_git_snapshot(context.config)
            if before_git_snapshot is None:
                if not context.is_worktree_clean(context.config):
                    return StepExecutionResult(
                        outcome=StepOutcome.DIRTY_WORKTREE,
                        failure_reason={
                            FR_CODE: FAILURE_DIRTY_WORKTREE,
                            FR_MESSAGE: "ANALYSIS requires a clean tree when no Git baseline is available.",
                        },
                        message=f"Blocked: {step_id} cannot establish an analysis baseline.",
                        message_is_error=True,
                    )
                clean_fallback = True

    agent_name = step_yaml.get(FIELD_AGENT)
    if agent_name is None and context.step_prompt.strip():
        agent_name = AGENT_DEFAULT
    if agent_name is not None:
        agent_name = context.config.resolve_agent(agent_name)
    model = (
        context.config.resolve_model(step_yaml.get(FIELD_MODEL, MODEL_DEFAULT))
        if agent_name
        else None
    )

    extra_fields: dict[str, Any] = {}
    if step_yaml.get(FIELD_PRE_ANALYSIS):
        pre_analysis_result = context.pre_analysis_runner(
            step,
            automation_dir=context.automation_dir,
            working_dir=Path("."),
            timeout_seconds=context.config.pre_analysis_timeout_seconds,
        )
        extra_fields[PROGRESS_FIELD_PRE_ANALYSIS] = _pre_analysis_summary(pre_analysis_result)
        if not pre_analysis_result.ok:
            if pre_analysis_result.tree_modified:
                return StepExecutionResult(
                    outcome=StepOutcome.SCOPE_VIOLATION,
                    failure_reason={
                        FR_CODE: FAILURE_SCOPE_VIOLATION,
                        FR_MESSAGE: pre_analysis_result.failure_reason
                        or "ANALYSIS modified Git-visible source files.",
                    },
                    agent=agent_name,
                    extra_fields=extra_fields,
                    message=f"Analysis source change violation at {step_id}.",
                    message_is_error=True,
                )
            outcome = (
                StepOutcome.PRE_ANALYSIS_ERROR
                if _has_script_error(pre_analysis_result.command_results)
                else StepOutcome.PRE_ANALYSIS_FAILED
            )
            return StepExecutionResult(
                outcome=outcome,
                failure_reason={
                    FR_CODE: FAILURE_PRE_ANALYSIS_FAILED,
                    FR_MESSAGE: pre_analysis_result.failure_reason
                    or "Analysis pre-analysis failed.",
                },
                agent=agent_name,
                extra_fields=extra_fields,
                message=f"Analysis pre-analysis failed for {step_id}.",
                message_is_error=True,
            )

    if agent_name:
        request = AgentInvocationRequest(
            step_id=step_id,
            agent_name=agent_name,
            model=model or context.config.default_model,
            system_prompt_path=system_prompt_path_for_type(
                STEP_TYPE_ANALYSIS, context.automation_dir
            ),
            step_prompt=context.step_prompt,
            plan_context=context.plan_context,
            allowed_files=[],
            verification_commands=[],
            title=step.heading_title,
        )
        failure = _invoke(context, request, analysis=True)
        if failure is not None:
            return StepExecutionResult(
                outcome=failure.outcome,
                failure_reason=failure.failure_reason,
                agent=failure.agent,
                extra_fields=extra_fields,
                message=failure.message,
                message_is_error=True,
            )

    if not context.no_scope_enforcement and _analysis_changed(
        context,
        before_git_snapshot=before_git_snapshot,
        clean_fallback=clean_fallback,
    ):
        return StepExecutionResult(
            outcome=StepOutcome.SCOPE_VIOLATION,
            failure_reason={
                FR_CODE: FAILURE_SCOPE_VIOLATION,
                FR_MESSAGE: "ANALYSIS modified Git-visible source files.",
            },
            agent=agent_name,
            extra_fields=extra_fields,
            message=f"Analysis source change violation at {step_id}.",
            message_is_error=True,
        )

    return StepExecutionResult(
        agent=agent_name,
        extra_fields=extra_fields,
        message=f"Completed: {step_id} - {step.heading_title}",
    )


def execute_implementation_step(context: StepExecutionContext) -> StepExecutionResult:
    """Execute an IMPLEMENTATION step through verification and commit."""
    step = context.step
    step_yaml = step.yaml_block
    step_id = step_yaml[FIELD_ID]
    agent_name = context.config.resolve_agent(step_yaml.get(FIELD_AGENT, AGENT_DEFAULT))
    model = context.config.resolve_model(step_yaml.get(FIELD_MODEL, MODEL_DEFAULT))

    if step_yaml.get(FIELD_PRE_ANALYSIS):
        pre_analysis_result = context.pre_analysis_runner(
            step,
            automation_dir=context.automation_dir,
            working_dir=Path("."),
            timeout_seconds=context.config.pre_analysis_timeout_seconds,
        )
        if not pre_analysis_result.ok:
            outcome = (
                StepOutcome.PRE_ANALYSIS_ERROR
                if _has_script_error(pre_analysis_result.command_results)
                else StepOutcome.PRE_ANALYSIS_FAILED
            )
            return StepExecutionResult(
                outcome=outcome,
                failure_reason={
                    FR_CODE: (
                        FAILURE_DIRTY_WORKTREE
                        if pre_analysis_result.tree_modified
                        else FAILURE_VERIFICATION_FAILED
                    ),
                    FR_MESSAGE: pre_analysis_result.failure_reason
                    or "Pre-analysis failed.",
                },
                agent=agent_name,
                message=f"Pre-analysis failed for {step_id}.",
                message_is_error=True,
            )

    if context.change_detector is not None:
        context.change_detector.snapshot_before()

    request = AgentInvocationRequest(
        step_id=step_id,
        agent_name=agent_name,
        model=model,
        system_prompt_path=system_prompt_path_for_type(
            step_yaml.get(FIELD_TYPE), context.automation_dir
        ),
        step_prompt=context.step_prompt,
        plan_context=context.plan_context,
        allowed_files=step_yaml.get(FIELD_ALLOWED_FILES, []),
        verification_commands=step_yaml.get(FIELD_VERIFICATION, {}).get(FIELD_COMMANDS, []),
        title=step.heading_title,
    )
    failure = _invoke(context, request)
    if failure is not None:
        return failure

    if context.change_detector is not None:
        changed_files = context.change_detector.detect_changes()
        scope_violations = check_allowed_files(
            step_yaml.get(FIELD_ALLOWED_FILES, []), changed_files
        )
        if scope_violations:
            return StepExecutionResult(
                outcome=StepOutcome.SCOPE_VIOLATION,
                failure_reason={
                    FR_CODE: FAILURE_SCOPE_VIOLATION,
                    FR_MESSAGE: f"Scope violation: {[v.file_path for v in scope_violations]}",
                },
                agent=agent_name,
                message=f"Scope violation at {step_id}.",
                message_is_error=True,
            )

    verification_result = context.verification_runner(
        step, automation_dir=context.automation_dir, attempt=1
    )
    verification_attempts = [verification_result]
    fix_attempts = 0
    verification_has_script_error = _has_script_error(
        verification_result.command_results
    )

    if not verification_result.ok and not verification_has_script_error:
        failure_summary = {
            "commands": [
                {
                    "command": result.command,
                    "exit_code": result.exit_code,
                    "status": result.status,
                    "stdout_tail": result.stdout_tail,
                    "stderr_tail": result.stderr_tail,
                }
                for result in verification_result.command_results
            ],
        }
        retry_controller = RetryController(
            step=step,
            adapter=context.adapter,
            automation_dir=context.automation_dir,
            failure_summary=failure_summary,
            change_detector=context.change_detector,
            step_prompt=context.step_prompt,
            system_prompt_path=system_prompt_path_for_type(
                step_yaml.get(FIELD_TYPE), context.automation_dir
            ),
            plan_context=context.plan_context,
        )
        while (
            not verification_result.ok
            and not verification_has_script_error
            and retry_controller.should_retry()
        ):
            fix_result = retry_controller.attempt_fix()
            fix_attempts += 1
            if (
                fix_result.scope_violation
                or fix_result.blocked
                or fix_result.agent_result.status == AGENT_STATUS_FAILED
            ):
                break
            verification_result = context.verification_runner(
                step,
                automation_dir=context.automation_dir,
                attempt=fix_attempts + 1,
            )
            verification_attempts.append(verification_result)
            verification_has_script_error = _has_script_error(
                verification_result.command_results
            )

    verification_fields = {
        PROGRESS_FIELD_FIX_ATTEMPTS: fix_attempts,
        PROGRESS_FIELD_VERIFICATION: _verification_summary(
            VERIFY_PASS if verification_result.ok else VERIFY_FAIL,
            verification_attempts,
        ),
    }
    if not verification_result.ok:
        outcome = (
            StepOutcome.VERIFICATION_ERROR
            if verification_has_script_error
            else StepOutcome.VERIFICATION_FAILED
        )
        return StepExecutionResult(
            outcome=outcome,
            failure_reason={
                FR_CODE: FAILURE_VERIFICATION_FAILED,
                FR_MESSAGE: (
                    "Verification script error."
                    if verification_has_script_error
                    else "Verification failed after all retry attempts."
                ),
            },
            agent=agent_name,
            verification_status=VERIFY_FAIL,
            extra_fields=verification_fields,
            message=(
                f"Verification script error blocked {step_id}."
                if verification_has_script_error
                else f"Verification failed for {step_id}."
            ),
            message_is_error=True,
        )

    commit_sha = context.git_commit(
        step_id,
        step.heading_title,
        push=context.push_required,
        config=context.config,
    )
    verification_fields[PROGRESS_FIELD_COMMIT] = commit_sha
    return StepExecutionResult(
        agent=agent_name,
        verification_status=VERIFY_PASS,
        extra_fields=verification_fields,
        message=f"Completed: {step_id} - {step.heading_title}",
    )


STEP_HANDLER_REGISTRY: dict[str, StepHandler] = {
    STEP_TYPE_IMPLEMENTATION: execute_implementation_step,
    STEP_TYPE_ANALYSIS: execute_analysis_step,
}


def get_step_handler(step_type: str) -> StepHandler:
    """Return the registered handler for a runnable step type."""
    try:
        return STEP_HANDLER_REGISTRY[step_type]
    except KeyError as exc:
        raise ValueError(f"No step handler registered for type {step_type!r}.") from exc


def execute_step(context: StepExecutionContext) -> StepExecutionResult:
    """Dispatch one step to the handler registered for its metadata type."""
    return get_step_handler(context.step.yaml_block[FIELD_TYPE])(context)
