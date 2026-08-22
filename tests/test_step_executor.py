"""Tests for step-type execution and dispatch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tests.fake_agent import FakeAgentAdapter
from tests.helpers import (
    make_analysis_step,
    make_default_config,
    make_implementation_step,
    make_plan,
)
from tools.constants import STEP_TYPE_ANALYSIS, STEP_TYPE_IMPLEMENTATION
from tools.orchestrator.change_detector import FakeChangeDetector
from tools.orchestrator.step_executor import (
    StepExecutionContext,
    execute_step,
    get_step_handler,
)
from tools.plan_parser import parse_plan
from tools.run_plan import prepare_run, run


def _parse_step(step_block: str):
    parsed = parse_plan(make_plan(step_block))
    assert parsed.ok
    return parsed.steps[0]


def _context(
    tmp_path: Path,
    step_block: str,
    adapter: FakeAgentAdapter,
    detector: FakeChangeDetector,
) -> StepExecutionContext:
    step = _parse_step(step_block)
    return StepExecutionContext(
        step=step,
        adapter=adapter,
        automation_dir=tmp_path / ".automation",
        config=make_default_config(automation_dir=str(tmp_path / ".automation")),
        step_prompt="Execute the test step.",
        plan_context="Test context.",
        change_detector=detector,
        no_scope_enforcement=False,
        push_required=False,
        is_worktree_clean=lambda _config: True,
        git_commit=lambda *_args, **_kwargs: "abc123",
    )


def test_implementation_handler_accepts_only_allowed_changes(tmp_path: Path) -> None:
    adapter = FakeAgentAdapter()
    adapter.enqueue_done("STEP-001")
    context = _context(
        tmp_path,
        make_implementation_step(
            allowed_files=["src/allowed.py"],
            verification_commands=['"python -c \\"print(1)\\""'],
        ),
        adapter,
        FakeChangeDetector({"src/allowed.py": "modified"}),
    )

    result = execute_step(context)

    assert result.completed
    assert result.extra_fields["commit"] == "abc123"
    assert adapter.invocations[0].allowed_files == ["src/allowed.py"]


def test_analysis_handler_requires_no_changed_files(tmp_path: Path) -> None:
    adapter = FakeAgentAdapter()
    adapter.enqueue_done("STEP-001")
    context = _context(
        tmp_path,
        make_analysis_step(agent="default.wfrunner"),
        adapter,
        FakeChangeDetector({}),
    )

    result = execute_step(context)

    assert result.completed
    assert adapter.invocations[0].allowed_files == []
    assert "commit" not in result.extra_fields


@pytest.mark.parametrize("step_type", [STEP_TYPE_IMPLEMENTATION, STEP_TYPE_ANALYSIS])
def test_registry_lookup_by_step_type(step_type: str) -> None:
    handler = get_step_handler(step_type)

    assert callable(handler)
    assert step_type.lower() in handler.__name__


@pytest.mark.parametrize("step_type", [STEP_TYPE_IMPLEMENTATION, STEP_TYPE_ANALYSIS])
def test_run_uses_injected_adapter_factory_for_each_step_type(
    tmp_path: Path,
    step_type: str,
) -> None:
    step_block = (
        make_implementation_step(
            verification_commands=['"python -c \\"print(1)\\""']
        )
        if step_type == STEP_TYPE_IMPLEMENTATION
        else make_analysis_step(agent="default.wfrunner", model="default")
    )
    plan_path = tmp_path / "plan.md"
    plan_path.write_text(make_plan(step_block), encoding="utf-8")
    automation_dir = tmp_path / ".automation"
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "system_prompt.implementation.md").write_text(
        "Implementation prompt.", encoding="utf-8"
    )
    (prompts_dir / "system_prompt.analysis.md").write_text(
        "Analysis prompt.", encoding="utf-8"
    )
    config = make_default_config(automation_dir=str(automation_dir))
    context = prepare_run(str(plan_path), config)
    adapter = FakeAgentAdapter()
    adapter.enqueue_done("STEP-001")
    factory_calls: list[tuple[object, Path]] = []

    def adapter_factory(factory_config, factory_automation_dir):
        factory_calls.append((factory_config, factory_automation_dir))
        return adapter

    with (
        patch("tools.run_plan._is_worktree_clean", return_value=True),
        patch("tools.run_plan._git_commit", return_value="abc123"),
    ):
        exit_code = run(
            context,
            one_step=True,
            no_scope_enforcement=True,
            adapter_factory=adapter_factory,
        )

    assert exit_code == 0
    assert factory_calls == [(config, automation_dir)]
    assert adapter.invocations[0].step_id == "STEP-001"
