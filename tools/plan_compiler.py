"""Compile Markdown implementation plans into machine-readable artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema

from tools.constants import (
    FIELD_AGENT,
    FIELD_DESCRIPTION,
    FIELD_ID,
    FIELD_METADATA,
    FIELD_MODEL,
    FIELD_PLAN_DESCRIPTION,
    FIELD_PROMPT,
    FIELD_REVIEW_GUIDANCE,
    FIELD_SCHEMA_VERSION,
    FIELD_SOURCE_FILE,
    FIELD_SOURCE_SHA256,
    FIELD_TITLE,
    FIELD_TYPE,
    PROGRESS_FIELD_STEPS,
    STEP_TYPE_HUMAN_GATE,
    STEP_TYPE_IMPLEMENTATION,
)
from tools.data_path import get_project_root, require_runtime_resource
from tools.plan_parser import ParsedStep, parse_plan_file
from tools.plan_validator import validate_plan


COMPILED_PLAN_FILENAME = "plan.compiled.json"
PLAN_CONTEXT_FILENAME = "plan-context.md"


class CompiledPlanError(Exception):
    """Base exception for compiled-plan failures."""


class CompiledPlanDriftError(CompiledPlanError):
    """Raised when source Markdown no longer matches the compiled artifact."""


def compile_plan(
    plan_path: str | Path,
    *,
    automation_dir: Path,
    protected_paths: tuple[str, ...] | list[str] | None = None,
) -> Path:
    """Parse, validate, and write a compiled plan artifact.

    Returns the path to ``plan.compiled.json``.
    """
    compiled = compile_plan_data(plan_path, protected_paths=protected_paths)

    automation_dir.mkdir(parents=True, exist_ok=True)
    compiled_path = automation_dir / COMPILED_PLAN_FILENAME
    compiled_path.write_text(json.dumps(compiled, indent=2), encoding="utf-8")

    context_path = automation_dir / PLAN_CONTEXT_FILENAME
    context_path.write_text(compiled[FIELD_PLAN_DESCRIPTION], encoding="utf-8")

    return compiled_path


def compile_plan_data(
    plan_path: str | Path,
    *,
    protected_paths: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """Parse and validate a plan, returning compiled data without writing it."""
    source_path = Path(plan_path)
    parse_result = parse_plan_file(source_path)
    validation = validate_plan(
        parse_result,
        schemas_dir=get_project_root() / "schemas",
        protected_paths=protected_paths,
    )
    if not validation.ok:
        messages = "; ".join(error.message for error in validation.errors)
        raise CompiledPlanError(f"Plan validation failed: {messages}")

    source_text = source_path.read_text(encoding="utf-8")
    plan_description = _extract_plan_description(source_text)
    if not plan_description:
        raise CompiledPlanError("Project description is required and cannot be empty.")

    compiled = {
        FIELD_SCHEMA_VERSION: 1,
        FIELD_SOURCE_FILE: str(source_path),
        FIELD_SOURCE_SHA256: _source_sha256(source_path),
        FIELD_PLAN_DESCRIPTION: plan_description,
        PROGRESS_FIELD_STEPS: [
            _compile_step(step, source_text)
            for step in parse_result.steps
        ],
    }
    _validate_compiled_plan(compiled)
    return compiled


def load_compiled_plan_for_run(
    plan_path: str | Path,
    *,
    automation_dir: Path,
    protected_paths: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """Load a compiled plan for execution, auto-compiling if missing."""
    source_path = Path(plan_path)
    compiled_path = automation_dir / COMPILED_PLAN_FILENAME
    if not compiled_path.exists():
        compile_plan(source_path, automation_dir=automation_dir, protected_paths=protected_paths)

    compiled = json.loads(compiled_path.read_text(encoding="utf-8"))
    _validate_compiled_plan(compiled)
    expected_sha = _source_sha256(source_path)
    if compiled.get(FIELD_SOURCE_SHA256) != expected_sha:
        raise CompiledPlanDriftError(
            "Compiled plan is stale; recompile before running or resuming."
        )
    return compiled


def _source_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compile_step(step: ParsedStep, source_text: str) -> dict[str, Any]:
    prompt = _extract_step_body(step, source_text)
    _validate_step_prompt(step, prompt)
    compiled: dict[str, Any] = {
        FIELD_ID: step.yaml_block[FIELD_ID],
        FIELD_TITLE: step.yaml_block[FIELD_TITLE],
        FIELD_PROMPT: prompt,
        FIELD_METADATA: step.yaml_block,
    }
    if step.yaml_block.get(FIELD_TYPE) == STEP_TYPE_HUMAN_GATE:
        review_guidance = step.yaml_block.get(
            FIELD_REVIEW_GUIDANCE
        ) or step.yaml_block.get(FIELD_DESCRIPTION)
        if review_guidance:
            compiled[FIELD_REVIEW_GUIDANCE] = review_guidance
    return compiled


def _validate_step_prompt(step: ParsedStep, prompt: str) -> None:
    """Require task prose for steps that invoke a worker agent."""
    step_type = step.yaml_block.get(FIELD_TYPE)
    invokes_agent = step_type == STEP_TYPE_IMPLEMENTATION or bool(
        step.yaml_block.get(FIELD_AGENT) or step.yaml_block.get(FIELD_MODEL)
    )
    if invokes_agent and not prompt:
        raise CompiledPlanError(
            f"Step {step.yaml_block[FIELD_ID]} requires non-empty task prose because it invokes an agent."
        )


def _extract_plan_description(source_text: str) -> str:
    lines = source_text.splitlines()
    for index, line in enumerate(lines):
        if line.strip().lower() == "## project description":
            description_lines: list[str] = []
            for candidate in lines[index + 1:]:
                if candidate.startswith("## "):
                    break
                description_lines.append(candidate)
            return "\n".join(description_lines).strip()
    for index, line in enumerate(lines):
        if line.strip().lower() == "## implementation plan":
            return "\n".join(lines[:index]).strip()
    return ""


def _extract_step_body(step: ParsedStep, source_text: str) -> str:
    """Lift the step's Markdown task prose, excluding its YAML metadata block.

    Captures prose both before and after the YAML fence so the compiled prompt
    works whether authors place the task description above or below the block.
    """
    lines = source_text.splitlines()
    heading_idx = step.heading_line_number - 1
    fence_open_idx = step.yaml_line_number - 2

    pre_lines = (
        lines[heading_idx + 1:fence_open_idx]
        if fence_open_idx > heading_idx
        else []
    )

    close_idx = step.yaml_line_number - 1
    while close_idx < len(lines) and not lines[close_idx].lstrip().startswith("```"):
        close_idx += 1

    end_idx = close_idx + 1
    while end_idx < len(lines):
        if lines[end_idx].startswith("### ") or lines[end_idx].startswith("## "):
            break
        end_idx += 1

    post_lines = lines[close_idx + 1:end_idx]
    return "\n".join([*pre_lines, *post_lines]).strip()


def _validate_compiled_plan(compiled: dict[str, Any]) -> None:
    schema_path = require_runtime_resource(
        Path("schemas") / "compiled-plan.schema.json",
        description="compiled plan schema",
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=compiled, schema=schema)