"""WaterfallRunner orchestration helpers for executing validated plan steps."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from tools.data_path import get_project_root
from tools.constants import (
    AGENT_STATUS_FAILED,
    FIELD_AGENT, FIELD_ALLOWED_FILES, FIELD_COMMANDS, FIELD_ID, FIELD_MODEL,
    FIELD_PRE_ANALYSIS, FIELD_TYPE, FIELD_VERIFICATION,
    AGENT_DEFAULT,
    MODEL_DEFAULT,
    FR_CODE, FR_MESSAGE,
    FAILURE_AGENT_BLOCKED, FAILURE_CHANGE_DETECTION_UNAVAILABLE,
    FAILURE_DIRTY_WORKTREE, FAILURE_HUMAN_GATE,
    FAILURE_INVALID_AGENT_RESULT, FAILURE_PRE_ANALYSIS_FAILED,
    FAILURE_SCOPE_VIOLATION, FAILURE_VERIFICATION_FAILED,
    PROGRESS_FIELD_AGENT, PROGRESS_FIELD_COMMIT, PROGRESS_FIELD_COMPLETED_AT,
    PROGRESS_FIELD_FAILURE_REASON, PROGRESS_FIELD_FIX_ATTEMPTS, PROGRESS_FIELD_LAST_RUN_ID,
    PROGRESS_FIELD_MODEL, PROGRESS_FIELD_PLAN_FILE, PROGRESS_FIELD_PRE_ANALYSIS,
    PROGRESS_FIELD_SCHEMA_VERSION, PROGRESS_FIELD_STARTED_AT, PROGRESS_FIELD_STATE,
    PROGRESS_FIELD_STEPS, PROGRESS_FIELD_VERIFICATION,
    STATE_BLOCKED, STATE_DONE, STATE_FAILED, STATE_IN_PROGRESS, STATE_TODO,
    STOP_AGENT_BLOCKED, STOP_ALL_COMPLETE, STOP_BLOCKED, STOP_DIRTY_WORKTREE,
    STOP_FAILED, STOP_HUMAN_GATE, STOP_INVALID_AGENT_RESULT,
    STOP_ONE_STEP, STOP_PRE_ANALYSIS_FAILED, STOP_SCOPE_VIOLATION,
    STOP_VERIFICATION_FAILED,
    ScriptOutcome,
    STEP_TYPE_ANALYSIS,
    VERIFY_FAIL, VERIFY_PASS,
)
from tools.plan_parser import ParsedStep, parse_plan_file
from tools.plan_validator import validate_plan
from tools.config import WaterfallRunnerConfig
from tools.orchestrator.agent_adapter import AgentAdapter, AgentInvocationRequest
from tools.orchestrator.agent_invocation import invoke_agent
from tools.orchestrator.change_detector import ChangeDetector
from tools.orchestrator.copilot_cli_adapter import CopilotCliAdapter
from tools.orchestrator.git import (
    ConfiguredGitChangeDetector as _ConfiguredGitChangeDetector,
    git_commit as _git_commit,
    git_timeout as _git_timeout,
    is_worktree_clean as _is_worktree_clean,
)
from tools.orchestrator.pre_analysis_runner import run_pre_analysis
from tools.orchestrator.progress_manager import ProgressValidationError, init_step_progress, load_progress, save_progress
from tools.orchestrator.report_generator import generate_whole_plan_report
from tools.orchestrator.retry_controller import RetryController
from tools.orchestrator.run_logger import append_log_entry
from tools.orchestrator.scope_enforcer import check_allowed_files, check_protected_files
from tools.orchestrator.step_selector import select_next_step
from tools.orchestrator.verification import VerificationResult, run_verification
from tools.plan_compiler import CompiledPlanDriftError, CompiledPlanError, load_compiled_plan_for_run


def _generate_run_id() -> str:
    """Generate a unique run ID based on the current UTC time."""
    return datetime.now(timezone.utc).strftime("RUN-%Y-%m-%dT%H:%M:%SZ")


class ChangeDetectionUnavailableError(RuntimeError):
    """Raised when Git cannot provide the change data required for scope enforcement."""


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


def _verification_attempt_status(result: VerificationResult) -> str:
    """Return the schema status for a verification attempt."""
    if result.ok:
        return VERIFY_PASS

    for command_result in result.command_results:
        if command_result.status != VERIFY_PASS:
            return command_result.status

    return VERIFY_FAIL


def _verification_summary(status: str, attempts: list[VerificationResult]) -> dict[str, Any]:
    """Build the progress.json verification summary from executed attempts."""
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


class _ScriptCommandResult(Protocol):
    outcome: ScriptOutcome


def _has_script_error(command_results: Iterable[_ScriptCommandResult]) -> bool:
    return any(command_result.outcome == ScriptOutcome.ERROR for command_result in command_results)


def _analysis_git_snapshot(config: WaterfallRunnerConfig) -> str | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            capture_output=True,
            text=True,
            timeout=_git_timeout(config),
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None
    return result.stdout


def _analysis_changed(
    *,
    change_detector: ChangeDetector | None,
    before_git_snapshot: str | None,
    clean_fallback: bool,
    config: WaterfallRunnerConfig,
) -> bool:
    if change_detector is not None:
        return bool(change_detector.detect_changes())
    if before_git_snapshot is not None:
        after_git_snapshot = _analysis_git_snapshot(config)
        return after_git_snapshot is None or after_git_snapshot != before_git_snapshot
    if clean_fallback:
        return not _is_worktree_clean(config)
    return True


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


def _load_resume_progress(progress_path: Path) -> tuple[dict[str, Any] | None, int | None]:
    """Load progress for --resume and convert invalid files into CLI errors."""
    try:
        return load_progress(progress_path), None
    except ProgressValidationError as exc:
        print(f"INVALID_PROGRESS_FILE: {exc}", file=sys.stderr)
        return None, 2
    except json.JSONDecodeError as exc:
        print(f"INVALID_PROGRESS_FILE: Could not parse {progress_path}: {exc}", file=sys.stderr)
        return None, 2


def _check_resume_consistency(
    progress: dict[str, Any],
    steps: list[Any],
    plan_path: Path,
) -> int | None:
    """Validate and update progress so resume matches the current plan."""
    current_plan_file = str(plan_path)
    recorded_plan_file = progress.get(PROGRESS_FIELD_PLAN_FILE)
    if recorded_plan_file != current_plan_file:
        print(
            "Resume plan_file mismatch: "
            f"progress.json records {recorded_plan_file!r}, but CLI plan is {current_plan_file!r}.",
            file=sys.stderr,
        )
        return 2

    plan_step_ids = [step.yaml_block[FIELD_ID] for step in steps]
    plan_step_id_set = set(plan_step_ids)
    progress_steps = progress.setdefault(PROGRESS_FIELD_STEPS, {})

    for step_id in progress_steps:
        if step_id not in plan_step_id_set:
            print(
                f"Resume step mismatch: progress.json contains {step_id}, but that step is not in the plan.",
                file=sys.stderr,
            )
            return 2

    for step_id in plan_step_ids:
        if step_id not in progress_steps:
            progress_steps[step_id] = init_step_progress()

    progress[PROGRESS_FIELD_PLAN_FILE] = current_plan_file
    return None


def _automation_dir_from_config(config_automation_dir: str) -> Path:
    """Return the configured automation directory."""
    return Path(config_automation_dir)


_SYSTEM_PROMPT_IMPLEMENTATION = "system_prompt.implementation.md"
_SYSTEM_PROMPT_ANALYSIS = "system_prompt.analysis.md"


def _system_prompt_path_for_type(step_type: str | None, automation_dir: Path) -> str:
    """Return the scaffolded per-type system prompt path for a step type."""
    prompt_name = _SYSTEM_PROMPT_ANALYSIS if step_type == STEP_TYPE_ANALYSIS else _SYSTEM_PROMPT_IMPLEMENTATION
    candidates = [
        automation_dir.parent / "prompts" / prompt_name,
        Path(".wfrunner") / "prompts" / prompt_name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate.resolve())
    return str(candidates[0].resolve())


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
) -> dict[str, Any]:
    """Validate plan, initialize/load progress, create automation dir.

    Args:
        plan_path_str: Path to the implementation plan file.
        config: WaterfallRunnerConfig instance.
        resume: If True, load existing progress instead of starting fresh.

    Returns:
        A context dict with keys: plan_path, steps, progress, progress_path,
        automation_dir, log_path, run_id, config. On error, returns
        {"error": "message"}.
    """
    plan_path = Path(plan_path_str)
    if not plan_path.exists():
        return {"error": f"Plan file not found: {plan_path}"}

    _warn_if_protected_paths_disabled(config)

    automation_dir = _automation_dir_from_config(config.automation_dir)
    automation_dir.mkdir(parents=True, exist_ok=True)

    try:
        compiled_plan = load_compiled_plan_for_run(
            plan_path,
            automation_dir=automation_dir,
            protected_paths=config.protected_paths,
        )
    except CompiledPlanDriftError as exc:
        return {"error": f"Compiled plan drift detected: {exc}"}
    except CompiledPlanError as exc:
        return {"error": str(exc)}

    steps = _steps_from_compiled_plan(compiled_plan)
    if not steps:
        return {"error": "No steps found in implementation plan."}

    progress_path = automation_dir / "progress.json"
    log_path = automation_dir / "run-log.md"
    run_id = _generate_run_id()

    if resume and progress_path.exists():
        progress, load_error = _load_resume_progress(progress_path)
        if load_error is not None:
            return {"error": "Failed to load progress file for resume."}
        if progress is None:
            return {"error": "Failed to load progress file for resume."}
        consistency_error = _check_resume_consistency(progress, steps, plan_path)
        if consistency_error is not None:
            return {"error": "Resume consistency check failed."}
        progress[PROGRESS_FIELD_LAST_RUN_ID] = run_id
    else:
        progress = _init_progress(steps, str(plan_path), run_id)

    save_progress(progress_path, progress)

    return {
        "error": None,
        "plan_path": plan_path,
        "steps": steps,
        "progress": progress,
        "progress_path": progress_path,
        "automation_dir": automation_dir,
        "log_path": log_path,
        "run_id": run_id,
        "config": config,
        "compiled_plan": compiled_plan,
    }


def reset_run(config: Any) -> int:
    """Reset all steps in progress.json to TODO.

    Args:
        config: WaterfallRunnerConfig instance.

    Returns:
        0 on success, 1 on error.
    """
    automation_dir = _automation_dir_from_config(config.automation_dir)
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
    automation_dir = _automation_dir_from_config(config.automation_dir)
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


def run(
    ctx: dict[str, Any],
    *,
    one_step: bool = False,
    approve_human_gates: bool = False,
    no_scope_enforcement: bool = False,
    adapter: AgentAdapter | None = None,
    change_detector: ChangeDetector | None = None,
) -> int:
    """Execute the orchestrator loop.

    Callers should check prepared contexts for ``ctx.get("error")`` before
    calling run(). Direct error-context calls return the existing
    usage/validation exit code.

    Args:
        ctx: Prepared run context returned by prepare_run().
        one_step: If True, stop after the first successful implementation step.
        approve_human_gates: If True, auto-approve HUMAN_GATE steps after
            successful pre-analysis.
        no_scope_enforcement: If True, explicitly continue without Git-backed
            change detection or post-agent scope checks.
        adapter: Agent adapter to use. If None, a real adapter would be
            instantiated (not yet implemented in Phase 1).
        change_detector: Optional detector for post-agent file changes.

    Returns:
        Exit code: 0 success, 1 execution failure, 2 usage/validation error.
    """
    if ctx.get("error"):
        print(f"Error: {ctx['error']}", file=sys.stderr)
        return 2

    plan_path = Path(ctx["plan_path"])
    steps = ctx["steps"]
    progress = ctx["progress"]
    progress_path = Path(ctx["progress_path"])
    automation_dir = Path(ctx["automation_dir"])
    log_path = Path(ctx["log_path"])
    report_path = automation_dir / "whole-plan-report.md"
    config = ctx["config"]
    compiled_plan = ctx.get("compiled_plan", {})
    plan_context = compiled_plan.get("plan_description", "")
    compiled_prompts = {
        compiled_step["id"]: compiled_step.get("prompt", "")
        for compiled_step in compiled_plan.get("steps", [])
    }
    _warn_if_protected_paths_disabled(config)
    git_config = getattr(config, "git", None)
    push_required = bool(getattr(git_config, "push_required", True))

    default_adapter_created = adapter is None
    if adapter is None:
        adapter = CopilotCliAdapter(config, automation_dir)

    initialize_change_detector = change_detector is None and not no_scope_enforcement
    if no_scope_enforcement:
        change_detector = None

    stop_reason: str | None = None
    exit_code_override: int | None = None

    while True:
        selection = select_next_step(steps, progress.get(PROGRESS_FIELD_STEPS, {}))

        if selection is None:
            stop_reason = STOP_ALL_COMPLETE
            print("All steps complete.")
            break

        step = steps[selection.step_index]
        step_id = selection.step_id
        step_yaml = step.yaml_block
        is_analysis_step = step_yaml.get(FIELD_TYPE) == STEP_TYPE_ANALYSIS

        # Stop conditions.
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
            print(f"Stopped: {step_id} is blocked.")
            break

        if selection.action == "stop_failed":
            stop_reason = STOP_FAILED
            print(f"Stopped: {step_id} has failed.")
            break

        # Protected-file pre-check.
        protected_result = check_protected_files(step, selection.step_index, steps, protected_paths=config.protected_paths)
        if not protected_result.ok:
            stop_reason = "PROTECTED_FILE_VIOLATION"
            progress[PROGRESS_FIELD_STEPS].setdefault(step_id, {}).update({
                PROGRESS_FIELD_STATE: STATE_FAILED,
                PROGRESS_FIELD_COMPLETED_AT: _now_iso(),
                PROGRESS_FIELD_FAILURE_REASON: {
                    FR_CODE: FAILURE_SCOPE_VIOLATION,
                    FR_MESSAGE: f"Protected file violation: {[v.file_path for v in protected_result.violations]}",
                },
            })
            save_progress(progress_path, progress)
            print(f"Protected file violation at {step_id}.", file=sys.stderr)
            break

        if initialize_change_detector:
            try:
                change_detector = _create_default_change_detector(config)
            except ChangeDetectionUnavailableError as exc:
                stop_reason = STOP_BLOCKED
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

        if is_analysis_step:
            before_git_snapshot: str | None = None
            clean_fallback = False
            if not no_scope_enforcement:
                if change_detector is not None:
                    change_detector.snapshot_before()
                else:
                    before_git_snapshot = _analysis_git_snapshot(config)
                    if before_git_snapshot is None:
                        if not _is_worktree_clean(config):
                            stop_reason = STOP_DIRTY_WORKTREE
                            _finish_step(
                                progress,
                                progress_path,
                                log_path,
                                step_id,
                                STATE_BLOCKED,
                                failure_reason={
                                    FR_CODE: FAILURE_DIRTY_WORKTREE,
                                    FR_MESSAGE: "ANALYSIS requires a clean tree when no Git baseline is available.",
                                },
                                stop_reason=STOP_DIRTY_WORKTREE,
                            )
                            print(f"Blocked: {step_id} cannot establish an analysis baseline.", file=sys.stderr)
                            break
                        clean_fallback = True

            step_prompt = compiled_prompts.get(step_id, "")
            agent_name = step_yaml.get(FIELD_AGENT)
            if agent_name is None and step_prompt.strip():
                agent_name = AGENT_DEFAULT
            if agent_name is not None:
                agent_name = config.resolve_agent(agent_name)
            model = config.resolve_model(step_yaml.get(FIELD_MODEL, MODEL_DEFAULT)) if agent_name else None

            progress[PROGRESS_FIELD_STEPS].setdefault(step_id, {}).update({
                PROGRESS_FIELD_STATE: STATE_IN_PROGRESS,
                PROGRESS_FIELD_AGENT: agent_name,
                PROGRESS_FIELD_MODEL: model,
                PROGRESS_FIELD_STARTED_AT: _now_iso(),
            })
            save_progress(progress_path, progress)

            pre_analysis_summary: dict[str, Any] | None = None
            if step_yaml.get(FIELD_PRE_ANALYSIS):
                pre_analysis_result = run_pre_analysis(
                    step,
                    automation_dir=automation_dir,
                    working_dir=Path("."),
                    timeout_seconds=config.pre_analysis_timeout_seconds,
                )
                pre_analysis_summary = _pre_analysis_summary(pre_analysis_result)
                if not pre_analysis_result.ok:
                    if pre_analysis_result.tree_modified:
                        stop_reason = STOP_SCOPE_VIOLATION
                        _finish_step(
                            progress,
                            progress_path,
                            log_path,
                            step_id,
                            STATE_FAILED,
                            failure_reason={
                                FR_CODE: FAILURE_SCOPE_VIOLATION,
                                FR_MESSAGE: pre_analysis_result.failure_reason or "ANALYSIS modified Git-visible source files.",
                            },
                            agent=agent_name,
                            stop_reason=STOP_SCOPE_VIOLATION,
                            extra_fields={PROGRESS_FIELD_PRE_ANALYSIS: pre_analysis_summary},
                        )
                        print(f"Analysis source change violation at {step_id}.", file=sys.stderr)
                        break
                    if _has_script_error(pre_analysis_result.command_results):
                        stop_reason = STOP_BLOCKED
                        _finish_step(
                            progress,
                            progress_path,
                            log_path,
                            step_id,
                            STATE_BLOCKED,
                            failure_reason={
                                FR_CODE: FAILURE_PRE_ANALYSIS_FAILED,
                                FR_MESSAGE: pre_analysis_result.failure_reason or "Analysis pre-analysis script error.",
                            },
                            agent=agent_name,
                            stop_reason=STOP_BLOCKED,
                            extra_fields={PROGRESS_FIELD_PRE_ANALYSIS: pre_analysis_summary},
                        )
                        print(f"Analysis pre-analysis script error blocked {step_id}.", file=sys.stderr)
                        break

                    stop_reason = STOP_PRE_ANALYSIS_FAILED
                    _finish_step(
                        progress,
                        progress_path,
                        log_path,
                        step_id,
                        STATE_FAILED,
                        failure_reason={
                            FR_CODE: FAILURE_PRE_ANALYSIS_FAILED,
                            FR_MESSAGE: pre_analysis_result.failure_reason or "Analysis pre-analysis failed.",
                        },
                        agent=agent_name,
                        stop_reason=STOP_PRE_ANALYSIS_FAILED,
                        extra_fields={PROGRESS_FIELD_PRE_ANALYSIS: pre_analysis_summary},
                    )
                    print(f"Analysis pre-analysis failed for {step_id}.", file=sys.stderr)
                    break

            if agent_name:
                request = AgentInvocationRequest(
                    step_id=step_id,
                    agent_name=agent_name,
                    model=model or config.default_model,
                    system_prompt_path=_system_prompt_path_for_type(STEP_TYPE_ANALYSIS, automation_dir),
                    step_prompt=step_prompt,
                    plan_context=plan_context,
                    allowed_files=[],
                    verification_commands=[],
                    title=step.heading_title,
                )

                invocation_result = invoke_agent(adapter, request)
                if not invocation_result.ok:
                    if invocation_result.blocked:
                        stop_reason = STOP_AGENT_BLOCKED
                        _finish_step(
                            progress,
                            progress_path,
                            log_path,
                            step_id,
                            STATE_BLOCKED,
                            failure_reason={
                                FR_CODE: FAILURE_AGENT_BLOCKED,
                                FR_MESSAGE: invocation_result.agent_result.stop_condition_hit
                                if invocation_result.agent_result else "Analysis agent blocked.",
                            },
                            agent=agent_name,
                            stop_reason=STOP_AGENT_BLOCKED,
                        )
                    else:
                        stop_reason = STOP_FAILED
                        _finish_step(
                            progress,
                            progress_path,
                            log_path,
                            step_id,
                            STATE_FAILED,
                            failure_reason={
                                FR_CODE: FAILURE_INVALID_AGENT_RESULT,
                                FR_MESSAGE: invocation_result.failure_reason or "Analysis agent failed.",
                            },
                            agent=agent_name,
                            stop_reason=STOP_FAILED,
                        )
                    print(f"Analysis agent {'blocked' if invocation_result.blocked else 'failed'} at {step_id}.", file=sys.stderr)
                    break

            if not no_scope_enforcement and _analysis_changed(
                change_detector=change_detector,
                before_git_snapshot=before_git_snapshot,
                clean_fallback=clean_fallback,
                config=config,
            ):
                stop_reason = STOP_SCOPE_VIOLATION
                _finish_step(
                    progress,
                    progress_path,
                    log_path,
                    step_id,
                    STATE_FAILED,
                    failure_reason={
                        FR_CODE: FAILURE_SCOPE_VIOLATION,
                        FR_MESSAGE: "ANALYSIS modified Git-visible source files.",
                    },
                    agent=agent_name,
                    stop_reason=STOP_SCOPE_VIOLATION,
                    extra_fields={PROGRESS_FIELD_PRE_ANALYSIS: pre_analysis_summary} if pre_analysis_summary else None,
                )
                print(f"Analysis source change violation at {step_id}.", file=sys.stderr)
                break

            _finish_step(
                progress,
                progress_path,
                log_path,
                step_id,
                STATE_DONE,
                agent=agent_name,
                extra_fields={PROGRESS_FIELD_PRE_ANALYSIS: pre_analysis_summary} if pre_analysis_summary else None,
            )
            print(f"Completed: {step_id} — {step.heading_title}")

            if one_step:
                stop_reason = STOP_ONE_STEP
                break
            continue

        if not _is_worktree_clean(config):
            stop_reason = STOP_DIRTY_WORKTREE
            _finish_step(
                progress, progress_path, log_path, step_id, STATE_BLOCKED,
                failure_reason={
                    FR_CODE: FAILURE_DIRTY_WORKTREE,
                    FR_MESSAGE: "Git working tree must be clean before running an implementation step.",
                },
                stop_reason=STOP_DIRTY_WORKTREE,
            )
            print(f"Blocked: {step_id} requires a clean working tree.", file=sys.stderr)
            break

        # === Execute the step ===
        agent_name = config.resolve_agent(step_yaml.get(FIELD_AGENT, AGENT_DEFAULT))
        model = config.resolve_model(step_yaml.get(FIELD_MODEL, MODEL_DEFAULT))

        progress[PROGRESS_FIELD_STEPS].setdefault(step_id, {}).update({
            PROGRESS_FIELD_STATE: STATE_IN_PROGRESS,
            PROGRESS_FIELD_AGENT: agent_name,
            PROGRESS_FIELD_MODEL: model,
            PROGRESS_FIELD_STARTED_AT: _now_iso(),
        })
        save_progress(progress_path, progress)

        # 6. Pre-analysis.
        if step_yaml.get(FIELD_PRE_ANALYSIS):
            pre_analysis_result = run_pre_analysis(
                step,
                automation_dir=automation_dir,
                working_dir=Path("."),
                timeout_seconds=config.pre_analysis_timeout_seconds,
            )
            if not pre_analysis_result.ok:
                if _has_script_error(pre_analysis_result.command_results):
                    stop_reason = STOP_BLOCKED
                    _finish_step(
                        progress, progress_path, log_path, step_id, STATE_BLOCKED,
                        failure_reason={
                            FR_CODE: FAILURE_PRE_ANALYSIS_FAILED,
                            FR_MESSAGE: pre_analysis_result.failure_reason or "Pre-analysis script error.",
                        },
                        agent=agent_name,
                        stop_reason=STOP_BLOCKED,
                    )
                    print(f"Pre-analysis script error blocked {step_id}.", file=sys.stderr)
                    break

                stop_reason = STOP_PRE_ANALYSIS_FAILED
                _finish_step(
                    progress, progress_path, log_path, step_id, STATE_FAILED,
                    failure_reason={
                        FR_CODE: FAILURE_DIRTY_WORKTREE if pre_analysis_result.tree_modified else FAILURE_VERIFICATION_FAILED,
                        FR_MESSAGE: pre_analysis_result.failure_reason or "Pre-analysis detected tree modification.",
                    },
                    agent=agent_name,
                    stop_reason=STOP_PRE_ANALYSIS_FAILED,
                )
                print(f"Pre-analysis failed for {step_id}.", file=sys.stderr)
                break

        if change_detector is not None:
            change_detector.snapshot_before()

        # 7. Invoke agent.
        request = AgentInvocationRequest(
            step_id=step_id,
            agent_name=agent_name,
            model=model,
            system_prompt_path=_system_prompt_path_for_type(step_yaml.get(FIELD_TYPE), automation_dir),
            step_prompt=compiled_prompts.get(step_id, ""),
            plan_context=plan_context,
            allowed_files=step_yaml.get(FIELD_ALLOWED_FILES, []),
            verification_commands=step_yaml.get(FIELD_VERIFICATION, {}).get(FIELD_COMMANDS, []),
            title=step.heading_title,
        )

        try:
            invocation_result = invoke_agent(adapter, request)
        except FileNotFoundError as exc:
            if not default_adapter_created:
                raise
            stop_reason = STOP_AGENT_BLOCKED
            _finish_step(
                progress, progress_path, log_path, step_id, STATE_BLOCKED,
                failure_reason={
                    FR_CODE: FAILURE_AGENT_BLOCKED,
                    FR_MESSAGE: f"Copilot CLI command not found: {exc.filename}",
                },
                agent=agent_name,
                stop_reason=STOP_AGENT_BLOCKED,
            )
            print(f"Copilot CLI command not found: {exc.filename}", file=sys.stderr)
            exit_code_override = 2
            break

        if not invocation_result.ok:
            if invocation_result.blocked:
                stop_reason = STOP_AGENT_BLOCKED
                _finish_step(
                    progress, progress_path, log_path, step_id, STATE_BLOCKED,
                    failure_reason={
                        FR_CODE: FAILURE_AGENT_BLOCKED,
                        FR_MESSAGE: invocation_result.agent_result.stop_condition_hit
                        if invocation_result.agent_result else "Agent blocked.",
                    },
                    agent=agent_name,
                    stop_reason=STOP_AGENT_BLOCKED,
                )
            elif invocation_result.failed:
                stop_reason = STOP_FAILED
                _finish_step(
                    progress, progress_path, log_path, step_id, STATE_FAILED,
                    failure_reason={
                        FR_CODE: FAILURE_INVALID_AGENT_RESULT,
                        FR_MESSAGE: invocation_result.failure_reason or "Agent returned FAILED.",
                    },
                    agent=agent_name,
                    stop_reason=STOP_FAILED,
                )
            else:
                stop_reason = STOP_INVALID_AGENT_RESULT
                _finish_step(
                    progress, progress_path, log_path, step_id, STATE_FAILED,
                    failure_reason={
                        FR_CODE: FAILURE_INVALID_AGENT_RESULT,
                        FR_MESSAGE: invocation_result.failure_reason or "Invalid agent result.",
                    },
                    agent=agent_name,
                    stop_reason=STOP_INVALID_AGENT_RESULT,
                )
            print(f"Agent {'blocked' if invocation_result.blocked else 'failed'} at {step_id}.", file=sys.stderr)
            if (
                default_adapter_created
                and invocation_result.blocked
                and invocation_result.agent_result is not None
                and invocation_result.agent_result.stop_condition_hit is not None
                and invocation_result.agent_result.stop_condition_hit.startswith("copilot_exit_code_")
            ):
                exit_code_override = 2
            break

        if change_detector is not None:
            changed_files = change_detector.detect_changes()
            scope_violations = check_allowed_files(step_yaml.get(FIELD_ALLOWED_FILES, []), changed_files)
            if scope_violations:
                stop_reason = STOP_SCOPE_VIOLATION
                _finish_step(
                    progress, progress_path, log_path, step_id, STATE_FAILED,
                    failure_reason={
                        FR_CODE: FAILURE_SCOPE_VIOLATION,
                        FR_MESSAGE: f"Scope violation: {[v.file_path for v in scope_violations]}",
                    },
                    agent=agent_name,
                    stop_reason=STOP_SCOPE_VIOLATION,
                )
                print(f"Scope violation at {step_id}.", file=sys.stderr)
                break

        # 8. Verification.
        verification_result = run_verification(step, automation_dir=automation_dir, attempt=1)
        verification_attempts = [verification_result]

        # 9. Retry loop on verification failure.
        fix_attempts = 0
        verification_has_script_error = _has_script_error(verification_result.command_results)
        if not verification_result.ok and not verification_has_script_error:
            failure_summary = {
                "commands": [
                    {
                        "command": cr.command,
                        "exit_code": cr.exit_code,
                        "status": cr.status,
                        "stdout_tail": cr.stdout_tail,
                        "stderr_tail": cr.stderr_tail,
                    }
                    for cr in verification_result.command_results
                ],
            }
            retry_ctrl = RetryController(
                step=step,
                adapter=adapter,
                automation_dir=automation_dir,
                failure_summary=failure_summary,
                change_detector=change_detector,
                step_prompt=compiled_prompts.get(step_id, ""),
                system_prompt_path=_system_prompt_path_for_type(step_yaml.get(FIELD_TYPE), automation_dir),
                plan_context=plan_context,
            )
            while (
                not verification_result.ok
                and not verification_has_script_error
                and retry_ctrl.should_retry()
            ):
                fix_result = retry_ctrl.attempt_fix()
                fix_attempts += 1

                if fix_result.scope_violation or fix_result.blocked or fix_result.agent_result.status == AGENT_STATUS_FAILED:
                    break

                verification_result = run_verification(
                    step,
                    automation_dir=automation_dir,
                    attempt=fix_attempts + 1,
                )
                verification_attempts.append(verification_result)
                verification_has_script_error = _has_script_error(verification_result.command_results)

        if not verification_result.ok:
            if verification_has_script_error:
                stop_reason = STOP_BLOCKED
                _finish_step(
                    progress, progress_path, log_path, step_id, STATE_BLOCKED,
                    failure_reason={
                        FR_CODE: FAILURE_VERIFICATION_FAILED,
                        FR_MESSAGE: "Verification script error.",
                    },
                    agent=agent_name,
                    verification_status=VERIFY_FAIL,
                    stop_reason=STOP_BLOCKED,
                    extra_fields={
                        PROGRESS_FIELD_FIX_ATTEMPTS: fix_attempts,
                        PROGRESS_FIELD_VERIFICATION: _verification_summary(VERIFY_FAIL, verification_attempts),
                    },
                )
                print(f"Verification script error blocked {step_id}.", file=sys.stderr)
            else:
                stop_reason = STOP_VERIFICATION_FAILED
                _finish_step(
                    progress, progress_path, log_path, step_id, STATE_FAILED,
                    failure_reason={
                        FR_CODE: FAILURE_VERIFICATION_FAILED,
                        FR_MESSAGE: "Verification failed after all retry attempts.",
                    },
                    agent=agent_name,
                    verification_status=VERIFY_FAIL,
                    stop_reason=STOP_VERIFICATION_FAILED,
                    extra_fields={
                        PROGRESS_FIELD_FIX_ATTEMPTS: fix_attempts,
                        PROGRESS_FIELD_VERIFICATION: _verification_summary(VERIFY_FAIL, verification_attempts),
                    },
                )
                print(f"Verification failed for {step_id}.", file=sys.stderr)
            break

        # 10. Step succeeded — commit the step's work.
        commit_sha = _git_commit(step_id, step.heading_title, push=push_required, config=config)

        _finish_step(
            progress, progress_path, log_path, step_id, STATE_DONE,
            agent=agent_name,
            verification_status=VERIFY_PASS,
            extra_fields={
                PROGRESS_FIELD_FIX_ATTEMPTS: fix_attempts,
                PROGRESS_FIELD_VERIFICATION: _verification_summary(VERIFY_PASS, verification_attempts),
                PROGRESS_FIELD_COMMIT: commit_sha,
            },
        )
        print(f"Completed: {step_id} — {step.heading_title}")

        # One-step mode: stop after first successful step.
        if one_step:
            stop_reason = STOP_ONE_STEP
            break

    generate_whole_plan_report(report_path, progress, stop_reason=stop_reason)
    print(f"Whole-plan report written to {report_path}")

    if exit_code_override is not None:
        return exit_code_override
    return 0 if stop_reason in (STOP_ALL_COMPLETE, STOP_ONE_STEP, STOP_HUMAN_GATE, None) else 1
