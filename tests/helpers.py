"""Test helpers — shared utilities and plan generators for orchestrator TDD."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

from tools.config import (
    BUILTIN_ALLOW_TOOLS,
    BUILTIN_DENY_TOOLS,
    CopilotCliConfig,
    GitConfig,
    WaterfallRunnerConfig,
)
from tools.constants import (
    FIELD_COMMANDS,
    FIELD_SCHEMA_VERSION,
    FIELD_TYPE,
    PA_FIELD_FAIL_ON_NONZERO,
    PA_FIELD_ID,
    PA_FIELD_PURPOSE,
    PA_FIELD_RUN,
    PROGRESS_FIELD_LAST_RUN_ID,
    PROGRESS_FIELD_PLAN_FILE,
    PROGRESS_FIELD_SCHEMA_VERSION,
    PROGRESS_FIELD_STEPS,
    STEP_TYPE_HUMAN_GATE,
    STEP_TYPE_IMPLEMENTATION,
    VERIFY_PASS,
)
from tools.orchestrator.progress_manager import init_step_progress


# ---------------------------------------------------------------------------
# Default config helper
# ---------------------------------------------------------------------------

DEFAULT_TEST_PROTECTED_PATHS: tuple[str, ...] = (
    "schemas/",
    ".github/agents/",
    ".github/copilot-instructions.md",
    "prompts/",
    ".wfrunner/wfrunner.toml",
)


def make_default_config(**overrides: Any) -> WaterfallRunnerConfig:
    """Build a WaterfallRunnerConfig with standard test defaults.

    Accepts keyword overrides for any field.
    """
    defaults = {
        "default_model": "default",
        "automation_dir": ".wfrunner/automation",
        "copilot_command": "copilot",
        "default_agent": "default.wfrunner",
        "copilot_cli": CopilotCliConfig(
            timeout_seconds=600,
            allow_tools=BUILTIN_ALLOW_TOOLS,
            deny_tools=BUILTIN_DENY_TOOLS,
        ),
        "protected_paths": DEFAULT_TEST_PROTECTED_PATHS,
        "git": GitConfig(push_required=True),
        "git_timeout_seconds": 30,
        "git_push_timeout_seconds": 60,
        "pre_analysis_timeout_seconds": 300,
    }
    defaults.update(overrides)
    return WaterfallRunnerConfig(**defaults)


# ---------------------------------------------------------------------------
# Progress file helpers
# ---------------------------------------------------------------------------

def make_progress(
    steps: dict[str, dict[str, Any]] | None = None,
    plan_file: str = "docs/implementation-plan.md",
    run_id: str = "RUN-2025-01-01T00:00:00Z",
) -> dict[str, Any]:
    """Build a progress.json-compatible dict.

    Args:
        steps: Per-step state entries keyed by step ID (e.g. ``STEP-001``).
            Each value should contain at least ``state``.
        plan_file: Repository-relative plan path.
        run_id: Run identifier.

    Returns:
        A progress dict conforming to ``schemas/progress.schema.json``.
    """
    if steps is None:
        steps = {}

    full_steps: dict[str, Any] = {}
    for step_id, partial in steps.items():
        full_steps[step_id] = _complete_step_progress(partial)

    return {
        PROGRESS_FIELD_SCHEMA_VERSION: 1,
        PROGRESS_FIELD_PLAN_FILE: plan_file,
        PROGRESS_FIELD_LAST_RUN_ID: run_id,
        PROGRESS_FIELD_STEPS: full_steps,
    }


def _complete_step_progress(partial: dict[str, Any]) -> dict[str, Any]:
    """Fill in defaults for a per-step progress entry."""
    defaults = init_step_progress()
    defaults.update(partial)
    return defaults


def write_progress(path: Path, progress: dict[str, Any]) -> None:
    """Write a progress dict to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(progress, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Plan text helpers (extended from conftest originals)
# ---------------------------------------------------------------------------

def make_implementation_step(
    step_id: str = "STEP-001",
    title: str = "Test step",
    agent: str = "default.wfrunner",
    model: str = "default",
    allowed_files: list[str] | None = None,
    verification_commands: list[str] | None = None,
    max_fix_attempts: int = 0,
    pre_analysis: dict[str, Any] | None = None,
    extra_yaml: str = "",
    task_prose: str = "Implement the requested change.",
) -> str:
    """Build a Markdown step block with IMPLEMENTATION YAML metadata.

    This is the canonical test helper; ``conftest.py`` delegates here.
    """
    if allowed_files is None:
        allowed_files = ["tools/__init__.py"]
    if verification_commands is None:
        verification_commands = ['"python -c \\"print(1)\\"\"']

    af_lines = "\n".join(f"  - {f}" for f in allowed_files)
    vc_lines = "\n".join(f"    - {c}" for c in verification_commands)

    pre_block = ""
    if pre_analysis is not None:
        cmds_yaml = ""
        for cmd in pre_analysis.get(FIELD_COMMANDS, []):
            cmds_yaml += f"    - {PA_FIELD_ID}: {cmd[PA_FIELD_ID]}\n"
            escaped_run = cmd[PA_FIELD_RUN].replace("'", "''")
            cmds_yaml += f"      {PA_FIELD_RUN}: '{escaped_run}'\n"
            cmds_yaml += f"      {PA_FIELD_PURPOSE}: {cmd[PA_FIELD_PURPOSE]}\n"
            cmds_yaml += f"      {PA_FIELD_FAIL_ON_NONZERO}: {str(cmd[PA_FIELD_FAIL_ON_NONZERO]).lower()}\n"
            if "include_output_in_prompt" in cmd:
                cmds_yaml += f"      include_output_in_prompt: {str(cmd['include_output_in_prompt']).lower()}\n"
            if "max_output_chars" in cmd:
                cmds_yaml += f"      max_output_chars: {cmd['max_output_chars']}\n"
            if cmd.get("output_files"):
                cmds_yaml += "      output_files:\n"
                for output_file in cmd["output_files"]:
                    cmds_yaml += f"        - {output_file}\n"
        pre_block = f"pre_analysis:\n  commands:\n{cmds_yaml}"

    # Build the step text without textwrap.dedent to avoid indentation
    # issues with multi-line embedded variables (pre_block, af_lines).
    yaml_lines = [
        f"{FIELD_SCHEMA_VERSION}: 1",
        f"id: {step_id}",
        f"title: {title}",
        f"{FIELD_TYPE}: {STEP_TYPE_IMPLEMENTATION}",
        f"agent: {agent}",
        f"model: {model}",
        "allowed_files:",
        af_lines,
    ]
    if pre_block:
        yaml_lines.append(pre_block.rstrip("\n"))
    yaml_lines.extend([
        "verification:",
        "  commands:",
        vc_lines,
        "retry:",
        f"  max_fix_attempts: {max_fix_attempts}",
    ])
    if extra_yaml:
        yaml_lines.append(extra_yaml.rstrip("\n"))

    yaml_body = "\n".join(yaml_lines)
    body = f"\n\n{task_prose.strip()}" if task_prose.strip() else ""
    return f"### {step_id} — {title}\n\n```yaml\n{yaml_body}\n```{body}\n"


def make_analysis_step(
    step_id: str = "STEP-001",
    title: str = "Analysis step",
    artifact_files: list[str] | None = None,
    pre_analysis: dict[str, Any] | None = None,
    agent: str | None = None,
    model: str | None = None,
    extra_yaml: str = "",
    task_prose: str | None = None,
) -> str:
    """Build a Markdown step block with ANALYSIS YAML metadata."""
    if artifact_files is None:
        artifact_files = [".wfrunner/analysis/report.md"]

    artifact_lines = "\n".join(f"  - {artifact_file}" for artifact_file in artifact_files)
    yaml_lines = [
        f"{FIELD_SCHEMA_VERSION}: 1",
        f"id: {step_id}",
        f"title: {title}",
        f"{FIELD_TYPE}: ANALYSIS",
        "artifact_files:",
        artifact_lines,
    ]
    if agent is not None:
        yaml_lines.append(f"agent: {agent}")
    if model is not None:
        yaml_lines.append(f"model: {model}")
    if pre_analysis is not None:
        cmds_yaml = ""
        for cmd in pre_analysis.get(FIELD_COMMANDS, []):
            cmds_yaml += f"    - {PA_FIELD_ID}: {cmd[PA_FIELD_ID]}\n"
            escaped_run = cmd[PA_FIELD_RUN].replace("'", "''")
            cmds_yaml += f"      {PA_FIELD_RUN}: '{escaped_run}'\n"
            cmds_yaml += f"      {PA_FIELD_PURPOSE}: {cmd[PA_FIELD_PURPOSE]}\n"
            cmds_yaml += f"      {PA_FIELD_FAIL_ON_NONZERO}: {str(cmd[PA_FIELD_FAIL_ON_NONZERO]).lower()}\n"
            if cmd.get("output_files"):
                cmds_yaml += "      output_files:\n"
                for output_file in cmd["output_files"]:
                    cmds_yaml += f"        - {output_file}\n"
        yaml_lines.append(f"pre_analysis:\n  commands:\n{cmds_yaml}".rstrip("\n"))
    if extra_yaml:
        yaml_lines.append(extra_yaml.rstrip("\n"))

    yaml_body = "\n".join(yaml_lines)
    body_text = task_prose
    if body_text is None and (agent is not None or model is not None):
        body_text = "Analyze the requested evidence."
    body = f"\n\n{body_text.strip()}" if body_text and body_text.strip() else ""
    return f"### {step_id} — {title}\n\n```yaml\n{yaml_body}\n```{body}\n"


def make_human_gate_step(
    step_id: str = "STEP-001",
    title: str = "Review step",
    review_guidance: str = "Human review required.",
) -> str:
    """Build a Markdown step block with HUMAN_GATE YAML metadata."""
    return textwrap.dedent(f"""\
        ### {step_id} — {title}

        ```yaml
        schema_version: 1
        id: {step_id}
        title: {title}
        type: {STEP_TYPE_HUMAN_GATE}
        review_guidance: {review_guidance}
        ```
    """)


def make_plan(
    *step_blocks: str,
    preamble: str = "# Test Plan\n\n## Project description\n\nTest project context.\n\n## Implementation plan\n\n",
) -> str:
    """Combine step blocks into a full plan document."""
    return preamble + "\n".join(step_blocks)


# ---------------------------------------------------------------------------
# Verification / command helpers
# ---------------------------------------------------------------------------

def make_verification_summary(
    step_id: str,
    attempt: int = 1,
    command_index: int = 0,
    command: str = "python -c 'print(1)'",
    exit_code: int = 0,
    status: str = VERIFY_PASS,
    duration: float = 0.1,
    stdout_tail: str = "",
    stderr_tail: str = "",
    log_path: str = "",
) -> dict[str, Any]:
    """Build a verification summary dict matching the contract."""
    return {
        "step_id": step_id,
        "attempt": attempt,
        "command_index": command_index,
        "command": command,
        "exit_code": exit_code,
        "status": status,
        "duration_seconds": duration,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "log_path": log_path,
    }


def make_pre_analysis_summary(
    step_id: str,
    command_id: str,
    command: str = "echo ok",
    exit_code: int = 0,
    status: str = VERIFY_PASS,
    duration: float = 0.1,
    log_path: str = "",
    included_in_prompt: bool = False,
) -> dict[str, Any]:
    """Build a pre-analysis summary dict matching the contract."""
    return {
        "step_id": step_id,
        "command_id": command_id,
        "command": command,
        "exit_code": exit_code,
        "status": status,
        "duration_seconds": duration,
        "log_path": log_path,
        "included_in_prompt": included_in_prompt,
    }
