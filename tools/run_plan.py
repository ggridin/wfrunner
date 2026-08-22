"""WaterfallRunner orchestration helpers for executing validated plan steps."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from tools.constants import (
    FIELD_AGENT, FIELD_COMMANDS, FIELD_ID, FIELD_MODEL,
    FIELD_PRE_ANALYSIS, FIELD_TYPE, FIELD_VERIFICATION,
    AGENT_DEFAULT,
    MODEL_DEFAULT,
    FR_CODE, FR_MESSAGE,
    FAILURE_CHANGE_DETECTION_UNAVAILABLE,
    FAILURE_DIRTY_WORKTREE, FAILURE_HUMAN_GATE,
    FAILURE_PRE_ANALYSIS_FAILED, FAILURE_SCOPE_VIOLATION,
    EXIT_USAGE_VALIDATION_ERROR,
    PROGRESS_FIELD_AGENT, PROGRESS_FIELD_COMPLETED_AT,
    PROGRESS_FIELD_FAILURE_REASON, PROGRESS_FIELD_LAST_RUN_ID,
    PROGRESS_FIELD_MODEL, PROGRESS_FIELD_PLAN_FILE, PROGRESS_FIELD_PRE_ANALYSIS,
    PROGRESS_FIELD_SCHEMA_VERSION, PROGRESS_FIELD_STARTED_AT, PROGRESS_FIELD_STATE,
    PROGRESS_FIELD_STEPS,
    STATE_BLOCKED, STATE_DONE, STATE_FAILED, STATE_IN_PROGRESS, STATE_TODO,
    STOP_ALL_COMPLETE, STOP_BLOCKED, STOP_FAILED, STOP_HUMAN_GATE,
    STOP_ONE_STEP, STOP_PRE_ANALYSIS_FAILED,
    ScriptOutcome,
    STEP_TYPE_ANALYSIS,
    VERIFY_FAIL, VERIFY_PASS,
)
from tools.plan_parser import ParsedStep
from tools.config import WaterfallRunnerConfig
from tools.orchestrator.agent_adapter import AgentAdapter
from tools.orchestrator.change_detector import ChangeDetector
from tools.orchestrator.copilot_cli_adapter import CopilotCliAdapter
from tools.orchestrator.git import (
    ConfiguredGitChangeDetector as _ConfiguredGitChangeDetector,
    git_commit as _git_commit,
    git_timeout as _git_timeout,
    is_worktree_clean as _is_worktree_clean,
)
from tools.orchestrator.pre_analysis_runner import run_pre_analysis
from tools.orchestrator.outcomes import STEP_OUTCOME_POLICY, StepOutcome
from tools.orchestrator.progress_manager import ProgressValidationError, init_step_progress, load_progress, save_progress
from tools.orchestrator.report_generator import generate_whole_plan_report
from tools.orchestrator.retry_controller import RetryController
from tools.orchestrator.run_logger import append_log_entry
from tools.orchestrator.scope_enforcer import check_protected_files
from tools.orchestrator.step_selector import select_next_step
from tools.orchestrator.step_executor import (
    StepExecutionContext,
    execute_step,
    system_prompt_path_for_type,
)
from tools.orchestrator.verification import run_verification
from tools.plan_compiler import CompiledPlanDriftError, CompiledPlanError, load_compiled_plan_for_run


def _generate_run_id() -> str:
    """Generate a unique run ID based on the current UTC time."""
    return datetime.now(timezone.utc).strftime("RUN-%Y-%m-%dT%H:%M:%SZ")


class ChangeDetectionUnavailableError(RuntimeError):
    """Raised when Git cannot provide the change data required for scope enforcement."""


class PrepareError(RuntimeError):
    """Raised when a run cannot be prepared."""

    def __init__(
        self,
        message: str,
        *,
        exit_code: int = EXIT_USAGE_VALIDATION_ERROR,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class RunContext:
    """Validated state required to execute a run."""

    plan_path: Path
    steps: list[ParsedStep]
    progress: dict[str, Any]
    progress_path: Path
    automation_dir: Path
    log_path: Path
    run_id: str
    config: WaterfallRunnerConfig
    compiled_plan: dict[str, Any]


def _create_default_change_detector(config: WaterfallRunnerConfig | None = None) -> ChangeDetector:
    """Create and validate the default Git-backed change detector."""
    try:
        detector = _ConfiguredGitChangeDetector(Path("."), _git_timeout(config))
        detector.detect_changes()
    except FileNotFoundError as exc:
        raise ChangeDetectionUnavailableError(
            "Git executable was not found; scope enforcement cannot detect file changes."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise ChangeDetectionUnavailableError(
            f"Git change detection failed with exit code {exc.returncode}."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ChangeDetectionUnavailableError(
            f"Git change detection timed out after {exc.timeout} seconds."
        ) from exc

    return detector


def _warn_if_protected_paths_disabled(config: WaterfallRunnerConfig) -> None:
    if not config.protected_paths:
        print(
            "Warning: protected-file enforcement is disabled because no protected_paths are configured.",
            file=sys.stderr,
        )


class _ScriptCommandResult(Protocol):
    outcome: ScriptOutcome


def _has_script_error(command_results: Iterable[_ScriptCommandResult]) -> bool:
    return any(command_result.outcome == ScriptOutcome.ERROR for command_result in command_results)


def _init_progress(
    steps: list[Any],
    plan_file: str,
    run_id: str,
) -> dict[str, Any]:
    """Create a fresh progress dict for all steps."""
    step_entries: dict[str, Any] = {}
    for step in steps:
        step_id = step.yaml_block[FIELD_ID]
        step_entries[step_id] = init_step_progress()
    return {
        PROGRESS_FIELD_SCHEMA_VERSION: 1,
        PROGRESS_FIELD_PLAN_FILE: plan_file,
        PROGRESS_FIELD_LAST_RUN_ID: run_id,
        PROGRESS_FIELD_STEPS: step_entries,
    }


def _steps_from_compiled_plan(compiled_plan: dict[str, Any]) -> list[ParsedStep]:
    """Convert compiled step records into the internal ParsedStep shape."""
    steps: list[ParsedStep] = []
    for index, step in enumerate(compiled_plan.get("steps", []), start=1):
        metadata = step["metadata"]
        steps.append(
            ParsedStep(
                heading_id=step["id"],
                heading_title=step["title"],
                heading_line_number=index,
                yaml_block=metadata,
                yaml_raw="",
                yaml_line_number=0,
            )
        )
    return steps


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _finish_step(
    progress: dict[str, Any],
    progress_path: Path,
    log_path: Path,
    step_id: str,
    state: str,
    *,
    failure_reason: dict[str, str] | None = None,
    agent: str | None = None,
    verification_status: str | None = None,
    stop_reason: str | None = None,
    extra_fields: dict[str, Any] | None = None,
) -> None:
    fields: dict[str, Any] = {
        PROGRESS_FIELD_STATE: state,
        PROGRESS_FIELD_COMPLETED_AT: _now_iso(),
    }
    if failure_reason is not None:
        fields[PROGRESS_FIELD_FAILURE_REASON] = failure_reason
    if extra_fields:
        fields.update(extra_fields)
    progress[PROGRESS_FIELD_STEPS].setdefault(step_id, init_step_progress()).update(fields)
    save_progress(progress_path, progress)
    append_log_entry(log_path, step_id, agent=agent, verification_status=verification_status, stop_reason=stop_reason)


def _pre_analysis_summary(pre_analysis_result: Any) -> dict[str, Any]:
    return {
        "status": VERIFY_PASS if pre_analysis_result.ok else VERIFY_FAIL,
        "commands": [
            {
                "command_id": command_result.command_id,
                "status": VERIFY_FAIL if command_result.status == VERIFY_FAIL else VERIFY_PASS,
                "summary_path": command_result.summary_path,
            }
            for command_result in pre_analysis_result.command_results
        ],
    }


def _finish_human_gate_with_pre_analysis(
    *,
    progress: dict[str, Any],
    progress_path: Path,
    log_path: Path,
    step: ParsedStep,
    step_id: str,
    pre_analysis_result: Any,
    approve_human_gates: bool,
) -> tuple[str | None, bool]:
    summary = _pre_analysis_summary(pre_analysis_result)

    if pre_analysis_result.ok:
        if approve_human_gates:
            _finish_step(
                progress,
                progress_path,
                log_path,
                step_id,
                STATE_DONE,
                extra_fields={PROGRESS_FIELD_PRE_ANALYSIS: summary},
            )
            print(f"Auto-approved HUMAN_GATE: {step_id} — {step.heading_title}")
            return None, True

        _finish_step(
            progress,
            progress_path,
            log_path,
            step_id,
            STATE_BLOCKED,
            failure_reason={FR_CODE: FAILURE_HUMAN_GATE, FR_MESSAGE: f"Human review required at {step_id}."},
            stop_reason=STOP_HUMAN_GATE,
            extra_fields={PROGRESS_FIELD_PRE_ANALYSIS: summary},
        )
        print(f"Stopped at HUMAN_GATE: {step_id} — {step.heading_title}")
        return STOP_HUMAN_GATE, False

    if _has_script_error(pre_analysis_result.command_results):
        _finish_step(
            progress,
            progress_path,
            log_path,
            step_id,
            STATE_BLOCKED,
            failure_reason={
                FR_CODE: FAILURE_PRE_ANALYSIS_FAILED,
                FR_MESSAGE: "HUMAN_GATE pre-analysis script error.",
            },
            stop_reason=STOP_BLOCKED,
            extra_fields={PROGRESS_FIELD_PRE_ANALYSIS: summary},
        )
        print(f"HUMAN_GATE pre-analysis error at {step_id}.", file=sys.stderr)
        return STOP_BLOCKED, False

    _finish_step(
        progress,
        progress_path,
        log_path,
        step_id,
        STATE_FAILED,
        failure_reason={
            FR_CODE: FAILURE_PRE_ANALYSIS_FAILED,
            FR_MESSAGE: f"HUMAN_GATE pre-analysis failed at {step_id}; human review gate was not approved.",
        },
        stop_reason=STOP_PRE_ANALYSIS_FAILED,
        extra_fields={PROGRESS_FIELD_PRE_ANALYSIS: summary},
    )
    print(f"HUMAN_GATE pre-analysis failed at {step_id}.", file=sys.stderr)
    return STOP_PRE_ANALYSIS_FAILED, False


def _load_resume_progress(progress_path: Path) -> dict[str, Any]:
    """Load progress for --resume, preserving validation diagnostics."""
    try:
        return load_progress(progress_path)
    except ProgressValidationError as exc:
        raise PrepareError(f"INVALID_PROGRESS_FILE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PrepareError(
            f"INVALID_PROGRESS_FILE: Could not parse {progress_path}: {exc}"
        ) from exc


def _check_resume_consistency(
    progress: dict[str, Any],
    steps: list[Any],
    plan_path: Path,
) -> None:
    """Validate and update progress so resume matches the current plan."""
    current_plan_file = str(plan_path)
    recorded_plan_file = progress.get(PROGRESS_FIELD_PLAN_FILE)
    if recorded_plan_file != current_plan_file:
        raise PrepareError(
            "Resume plan_file mismatch: "
            f"progress.json records {recorded_plan_file!r}, "
            f"but CLI plan is {current_plan_file!r}."
        )

    plan_step_ids = [step.yaml_block[FIELD_ID] for step in steps]
    plan_step_id_set = set(plan_step_ids)
    progress_steps = progress.setdefault(PROGRESS_FIELD_STEPS, {})

    for step_id in progress_steps:
        if step_id not in plan_step_id_set:
            raise PrepareError(
                f"Resume step mismatch: progress.json contains {step_id}, "
                "but that step is not in the plan."
            )

    for step_id in plan_step_ids:
        if step_id not in progress_steps:
            progress_steps[step_id] = init_step_progress()

    progress[PROGRESS_FIELD_PLAN_FILE] = current_plan_file


def _system_prompt_path_for_type(step_type: str | None, automation_dir: Path) -> str:
    """Return the scaffolded per-type system prompt path for a step type."""
    return system_prompt_path_for_type(step_type, automation_dir)


def _verification_step_for_current_shell(step: ParsedStep) -> ParsedStep:
    """Return a legacy normalized step without mutating parsed plan metadata."""
    verification = step.yaml_block.get(FIELD_VERIFICATION)
    if not isinstance(verification, dict):
        return step

    commands = verification.get(FIELD_COMMANDS)
    if not isinstance(commands, list):
        return step

    if sys.platform != "win32":
        return step

    normalized_commands = []
    for command in commands:
        if not isinstance(command, str):
            normalized_commands.append(command)
            continue

        chars: list[str] = []
        in_double_quotes = False
        for char in command:
            if char == '"':
                in_double_quotes = not in_double_quotes
            chars.append('"' if char == "'" and not in_double_quotes else char)
        normalized_commands.append("".join(chars))
    if normalized_commands == commands:
        return step

    normalized_verification = dict(verification)
    normalized_verification[FIELD_COMMANDS] = normalized_commands
    normalized_yaml = dict(step.yaml_block)
    normalized_yaml[FIELD_VERIFICATION] = normalized_verification
    return replace(step, yaml_block=normalized_yaml)


# ---------------------------------------------------------------------------
# Extracted functions (STEP-014)
# ---------------------------------------------------------------------------


def prepare_run(
    plan_path_str: str,
    config: Any,
    *,
    resume: bool = False,
) -> RunContext:
    """Validate plan, initialize/load progress, create automation dir.

    Args:
        plan_path_str: Path to the implementation plan file.
        config: WaterfallRunnerConfig instance.
        resume: If True, load existing progress instead of starting fresh.

    Returns:
        The validated context required by run().

    Raises:
        PrepareError: If the plan or resume state cannot be prepared.
    """
    plan_path = Path(plan_path_str)
    if not plan_path.exists():
        raise PrepareError(f"Plan file not found: {plan_path}")

    _warn_if_protected_paths_disabled(config)

    automation_dir = Path(config.automation_dir)
    automation_dir.mkdir(parents=True, exist_ok=True)

    try:
        compiled_plan = load_compiled_plan_for_run(
            plan_path,
            automation_dir=automation_dir,
            protected_paths=config.protected_paths,
        )
    except CompiledPlanDriftError as exc:
        raise PrepareError(f"Compiled plan drift detected: {exc}") from exc
    except CompiledPlanError as exc:
        raise PrepareError(str(exc)) from exc

    steps = _steps_from_compiled_plan(compiled_plan)
    if not steps:
        raise PrepareError("No steps found in implementation plan.")

    progress_path = automation_dir / "progress.json"
    log_path = automation_dir / "run-log.md"
    run_id = _generate_run_id()

    if resume and progress_path.exists():
        progress = _load_resume_progress(progress_path)
        _check_resume_consistency(progress, steps, plan_path)
        progress[PROGRESS_FIELD_LAST_RUN_ID] = run_id
    else:
        progress = _init_progress(steps, str(plan_path), run_id)

    save_progress(progress_path, progress)

    return RunContext(
        plan_path=plan_path,
        steps=steps,
        progress=progress,
        progress_path=progress_path,
        automation_dir=automation_dir,
        log_path=log_path,
        run_id=run_id,
        config=config,
        compiled_plan=compiled_plan,
    )


def reset_run(config: Any) -> int:
    """Reset all steps in progress.json to TODO.

    Args:
        config: WaterfallRunnerConfig instance.

    Returns:
        0 on success, 1 on error.
    """
    automation_dir = Path(config.automation_dir)
    progress_path = automation_dir / "progress.json"

    if not progress_path.exists():
        print("Error: No progress file found.", file=sys.stderr)
        return 1

    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    for step_data in progress.get(PROGRESS_FIELD_STEPS, {}).values():
        step_data[PROGRESS_FIELD_STATE] = STATE_TODO
    save_progress(progress_path, progress)
    print("All steps reset to TODO.")
    return 0


def reset_current_step(config: Any) -> int:
    """Reset the current in-progress or failed step to TODO.

    Args:
        config: WaterfallRunnerConfig instance.

    Returns:
        0 on success, 1 on error.
    """
    automation_dir = Path(config.automation_dir)
    progress_path = automation_dir / "progress.json"

    if not progress_path.exists():
        print("Error: No progress file found.", file=sys.stderr)
        return 1

    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    steps = progress.get(PROGRESS_FIELD_STEPS, {})

    for step_id, step_data in steps.items():
        state = step_data.get(PROGRESS_FIELD_STATE)
        if state in (STATE_FAILED, STATE_IN_PROGRESS, STATE_BLOCKED):
            step_data.update(init_step_progress())
            save_progress(progress_path, progress)
            print(f"Reset {step_id} from {state} to TODO.")
            return 0

    print("No step to reset (all are TODO or DONE).")
    return 0


class AdapterFactory(Protocol):
    """Factory for constructing the configured agent adapter."""

    def __call__(
        self,
        config: WaterfallRunnerConfig,
        automation_dir: Path,
    ) -> AgentAdapter: ...


def _default_adapter_factory(
    config: WaterfallRunnerConfig,
    automation_dir: Path,
) -> AgentAdapter:
    return CopilotCliAdapter(config, automation_dir)


def run(
    ctx: RunContext,
    *,
    one_step: bool = False,
    approve_human_gates: bool = False,
    no_scope_enforcement: bool = False,
    adapter: AgentAdapter | None = None,
    adapter_factory: AdapterFactory = _default_adapter_factory,
    change_detector: ChangeDetector | None = None,
) -> int:
    """Execute the orchestrator loop.

    Args:
        ctx: Prepared run context returned by prepare_run().
        one_step: If True, stop after the first successful implementation step.
        approve_human_gates: If True, auto-approve HUMAN_GATE steps after
            successful pre-analysis.
        no_scope_enforcement: If True, explicitly continue without Git-backed
            change detection or post-agent scope checks.
        adapter: Optional pre-built agent adapter.
        adapter_factory: Factory used when no adapter is supplied.
        change_detector: Optional detector for post-agent file changes.

    Returns:
        Exit code: 0 success, 1 execution failure, 2 usage/validation error.
    """
    plan_path = ctx.plan_path
    steps = ctx.steps
    progress = ctx.progress
    progress_path = ctx.progress_path
    automation_dir = ctx.automation_dir
    log_path = ctx.log_path
    report_path = automation_dir / "whole-plan-report.md"
    config = ctx.config
    compiled_plan = ctx.compiled_plan
    plan_context = compiled_plan.get("plan_description", "")
    compiled_prompts = {
        compiled_step["id"]: compiled_step.get("prompt", "")
        for compiled_step in compiled_plan.get("steps", [])
    }
    _warn_if_protected_paths_disabled(config)
    git_config = getattr(config, "git", None)
    push_required = bool(getattr(git_config, "push_required", True))

    if adapter is None:
        adapter = adapter_factory(config, automation_dir)

    initialize_change_detector = change_detector is None and not no_scope_enforcement
    if no_scope_enforcement:
        change_detector = None

    stop_reason: str | None = None
    exit_code = 0

    while True:
        selection = select_next_step(steps, progress.get(PROGRESS_FIELD_STEPS, {}))

        if selection is None:
            stop_reason = STOP_ALL_COMPLETE
            print("All steps complete.")
            break

        step = steps[selection.step_index]
        step_id = selection.step_id
        step_yaml = step.yaml_block
        if selection.action == "stop_human_gate":
            if step_yaml.get(FIELD_PRE_ANALYSIS):
                pa_result = run_pre_analysis(
                    step,
                    automation_dir=automation_dir,
                    working_dir=Path("."),
                    timeout_seconds=config.pre_analysis_timeout_seconds,
                )
                stop_reason, should_continue = _finish_human_gate_with_pre_analysis(
                    progress=progress,
                    progress_path=progress_path,
                    log_path=log_path,
                    step=step,
                    step_id=step_id,
                    pre_analysis_result=pa_result,
                    approve_human_gates=approve_human_gates,
                )
                if should_continue:
                    continue
                if stop_reason != STOP_HUMAN_GATE:
                    exit_code = 1
                break

            if approve_human_gates:
                _finish_step(progress, progress_path, log_path, step_id, STATE_DONE)
                print(f"Auto-approved HUMAN_GATE: {step_id} — {step.heading_title}")
                continue

            stop_reason = STOP_HUMAN_GATE
            _finish_step(
                progress, progress_path, log_path, step_id, STATE_BLOCKED,
                failure_reason={FR_CODE: FAILURE_HUMAN_GATE, FR_MESSAGE: f"Human review required at {step_id}."},
                stop_reason=STOP_HUMAN_GATE,
            )
            print(f"Stopped at HUMAN_GATE: {step_id} — {step.heading_title}")
            break

        if selection.action == "stop_blocked":
            stop_reason = STOP_BLOCKED
            exit_code = 1
            print(f"Stopped: {step_id} is blocked.")
            break

        if selection.action == "stop_failed":
            stop_reason = STOP_FAILED
            exit_code = 1
            print(f"Stopped: {step_id} has failed.")
            break

        protected_result = check_protected_files(step, selection.step_index, steps, protected_paths=config.protected_paths)
        if not protected_result.ok:
            policy = STEP_OUTCOME_POLICY[StepOutcome.SCOPE_VIOLATION]
            stop_reason = policy.stop_reason
            exit_code = policy.exit_code
            _finish_step(
                progress,
                progress_path,
                log_path,
                step_id,
                policy.state,
                failure_reason={
                    FR_CODE: FAILURE_SCOPE_VIOLATION,
                    FR_MESSAGE: f"Protected file violation: {[v.file_path for v in protected_result.violations]}",
                },
                stop_reason=policy.stop_reason,
            )
            print(f"Protected file violation at {step_id}.", file=sys.stderr)
            break

        if initialize_change_detector:
            try:
                change_detector = _create_default_change_detector(config)
            except ChangeDetectionUnavailableError as exc:
                stop_reason = STOP_BLOCKED
                exit_code = 1
                _finish_step(
                    progress,
                    progress_path,
                    log_path,
                    step_id,
                    STATE_BLOCKED,
                    failure_reason={
                        FR_CODE: FAILURE_CHANGE_DETECTION_UNAVAILABLE,
                        FR_MESSAGE: str(exc),
                    },
                    stop_reason=STOP_BLOCKED,
                )
                print(f"Blocked: {step_id}: {exc}", file=sys.stderr)
                break
            initialize_change_detector = False

        if step_yaml.get(FIELD_TYPE) != STEP_TYPE_ANALYSIS and not _is_worktree_clean(config):
            policy = STEP_OUTCOME_POLICY[StepOutcome.DIRTY_WORKTREE]
            stop_reason = policy.stop_reason
            exit_code = policy.exit_code
            _finish_step(
                progress, progress_path, log_path, step_id, policy.state,
                failure_reason={
                    FR_CODE: FAILURE_DIRTY_WORKTREE,
                    FR_MESSAGE: "Git working tree must be clean before running an implementation step.",
                },
                stop_reason=policy.stop_reason,
            )
            print(f"Blocked: {step_id} requires a clean working tree.", file=sys.stderr)
            break

        step_prompt = compiled_prompts.get(step_id, "")
        agent_name = step_yaml.get(FIELD_AGENT)
        if step_yaml.get(FIELD_TYPE) != STEP_TYPE_ANALYSIS:
            agent_name = config.resolve_agent(agent_name or AGENT_DEFAULT)
        elif agent_name is None and step_prompt.strip():
            agent_name = config.resolve_agent(AGENT_DEFAULT)
        elif agent_name is not None:
            agent_name = config.resolve_agent(agent_name)
        model = (
            config.resolve_model(step_yaml.get(FIELD_MODEL, MODEL_DEFAULT))
            if agent_name
            else None
        )

        progress[PROGRESS_FIELD_STEPS].setdefault(step_id, {}).update({
            PROGRESS_FIELD_STATE: STATE_IN_PROGRESS,
            PROGRESS_FIELD_AGENT: agent_name,
            PROGRESS_FIELD_MODEL: model,
            PROGRESS_FIELD_STARTED_AT: _now_iso(),
        })
        save_progress(progress_path, progress)

        result = execute_step(
            StepExecutionContext(
                step=step,
                adapter=adapter,
                automation_dir=automation_dir,
                config=config,
                step_prompt=step_prompt,
                plan_context=plan_context,
                change_detector=change_detector,
                no_scope_enforcement=no_scope_enforcement,
                push_required=push_required,
                is_worktree_clean=_is_worktree_clean,
                git_commit=_git_commit,
                pre_analysis_runner=run_pre_analysis,
                verification_runner=run_verification,
            )
        )
        policy = STEP_OUTCOME_POLICY[result.outcome] if result.outcome else None
        _finish_step(
            progress,
            progress_path,
            log_path,
            step_id,
            policy.state if policy else STATE_DONE,
            failure_reason=result.failure_reason,
            agent=result.agent,
            verification_status=result.verification_status,
            stop_reason=policy.stop_reason if policy else None,
            extra_fields=result.extra_fields,
        )
        if result.message:
            print(result.message, file=sys.stderr if result.message_is_error else sys.stdout)
        if policy:
            stop_reason = policy.stop_reason
            exit_code = policy.exit_code
            break

        if one_step:
            stop_reason = STOP_ONE_STEP
            break

    generate_whole_plan_report(report_path, progress, stop_reason=stop_reason)
    print(f"Whole-plan report written to {report_path}")

    return exit_code
