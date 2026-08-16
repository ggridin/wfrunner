"""Shared test fixtures for WaterfallRunner Phase 1 tests."""

import pathlib

import pytest

from tests.fake_agent import FakeAgentAdapter
from tests.helpers import (
    make_progress,
    write_progress,
)


@pytest.fixture(autouse=True)
def _prevent_real_git_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralize the orchestrator's per-step commit in tests.

    The run loop commits after every successful implementation step, and tests
    run from the repository root, so a real commit would mutate this repository.
    Replace the run_plan commit alias with a no-op returning None; tests that
    assert commit behavior re-patch it locally.
    """
    monkeypatch.setattr("tools.run_plan._git_commit", lambda *args, **kwargs: None)


@pytest.fixture
def project_root() -> pathlib.Path:
    """Return the project root directory."""
    return pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def schemas_dir(project_root: pathlib.Path) -> pathlib.Path:
    """Return the schemas directory."""
    return project_root / "schemas"


@pytest.fixture
def tmp_automation(tmp_path: pathlib.Path) -> pathlib.Path:
    """Return a temporary .automation directory for test isolation."""
    automation = tmp_path / ".automation"
    automation.mkdir()
    return automation


@pytest.fixture
def fake_agent() -> FakeAgentAdapter:
    """Return a fresh FakeAgentAdapter with no enqueued behaviors."""
    return FakeAgentAdapter()


@pytest.fixture
def tmp_plan(tmp_path: pathlib.Path):
    """Factory fixture: write a plan string to a temp file and return its path.

    Usage::

        def test_example(tmp_plan):
            plan_path = tmp_plan("# Test Plan\\n...")
    """
    def _write(content: str, filename: str = "implementation-plan.md") -> pathlib.Path:
        p = tmp_path / filename
        p.write_text(content, encoding="utf-8")
        return p
    return _write


@pytest.fixture
def tmp_progress(tmp_automation: pathlib.Path):
    """Factory fixture: write a progress dict and return the file path.

    Usage::

        def test_example(tmp_progress):
            progress_path = tmp_progress({"STEP-001": {"state": "DONE"}})
    """
    def _write(
        steps: dict | None = None,
        plan_file: str = "docs/implementation-plan.md",
    ) -> pathlib.Path:
        progress = make_progress(steps=steps, plan_file=plan_file)
        path = tmp_automation / "progress.json"
        write_progress(path, progress)
        return path
    return _write
