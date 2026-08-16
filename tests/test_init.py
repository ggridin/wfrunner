"""Tests for wfrunner init command."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from tools.init_project import init
from tools.wfrunner import main


@pytest.fixture(autouse=True)
def prompt_template_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_root = tmp_path / "_source"
    prompts_dir = source_root / "prompts"
    prompts_dir.mkdir(parents=True)
    for name in ("system_prompt.implementation.md", "system_prompt.analysis.md"):
        (prompts_dir / name).write_text(f"{name} template\n", encoding="utf-8")
    planner_dir = source_root / ".github" / "skills" / "wfrunner-planner"
    references_dir = planner_dir / "references"
    references_dir.mkdir(parents=True)
    (planner_dir / "SKILL.md").write_text("planner skill\n", encoding="utf-8")
    (references_dir / "plan-format.md").write_text("plan format\n", encoding="utf-8")
    monkeypatch.setattr("tools.init_project.get_project_root", lambda: source_root)


class TestInitCreatesWfrunnerToml:

    def test_init_creates_wfrunner_toml(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        result = init(target_dir=tmp_path)
        config_path = tmp_path / ".wfrunner" / "wfrunner.toml"
        assert config_path.exists()
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        assert "default_model" in data
        assert "automation_dir" in data
        assert "copilot_command" in data
        assert "default_agent" in data
        assert result == 0


class TestInitCreatesPromptTemplates:

    def test_init_copies_system_prompts(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        init(target_dir=tmp_path)
        prompts_dir = tmp_path / ".wfrunner" / "prompts"
        implementation = prompts_dir / "system_prompt.implementation.md"
        analysis = prompts_dir / "system_prompt.analysis.md"
        assert implementation.exists()
        assert implementation.stat().st_size > 0
        assert analysis.exists()
        assert analysis.stat().st_size > 0
        assert not (prompts_dir / "implement-step.md").exists()


class TestInitAppendsGitignore:

    def test_init_appends_gitignore(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        init(target_dir=tmp_path)
        gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        assert "# >>> WaterfallRunner managed >>>" in gitignore
        assert "# <<< WaterfallRunner managed <<<" in gitignore
        assert "/.wfrunner/" in gitignore
        assert ".github/agents/default.wfrunner.agent.md" in gitignore

    def test_init_gitignore_idempotent(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        init(target_dir=tmp_path)
        init(target_dir=tmp_path)
        gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        assert gitignore.count("# >>> WaterfallRunner managed >>>") == 1


class TestInitDoesNotOverwriteExistingConfig:

    def test_init_does_not_overwrite_existing_config(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        config_dir = tmp_path / ".wfrunner"
        config_dir.mkdir(parents=True)
        config_path = config_dir / "wfrunner.toml"
        config_path.write_text('default_model = "custom"\n', encoding="utf-8")
        init(target_dir=tmp_path)
        content = config_path.read_text(encoding="utf-8")
        assert 'default_model = "custom"' in content


class TestInitDoesNotOverwriteExistingPrompts:

    def test_init_does_not_overwrite_existing_prompts(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        prompts_dir = tmp_path / ".wfrunner" / "prompts"
        prompts_dir.mkdir(parents=True)
        implementation = prompts_dir / "system_prompt.implementation.md"
        implementation.write_text("custom content", encoding="utf-8")
        init(target_dir=tmp_path)
        assert implementation.read_text(encoding="utf-8") == "custom content"


class TestInitScaffoldsAgent:

    def test_init_scaffolds_agent(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        init(target_dir=tmp_path)
        agent_path = tmp_path / ".github" / "agents" / "default.wfrunner.agent.md"
        assert agent_path.exists()
        assert agent_path.stat().st_size > 0

    def test_init_does_not_overwrite_existing_agent(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        agent_dir = tmp_path / ".github" / "agents"
        agent_dir.mkdir(parents=True)
        agent_path = agent_dir / "default.wfrunner.agent.md"
        agent_path.write_text("custom agent", encoding="utf-8")
        init(target_dir=tmp_path)
        assert agent_path.read_text(encoding="utf-8") == "custom agent"


class TestInitScaffoldsPlannerSkill:

    def test_init_copies_wfrunner_planner_skill(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        init(target_dir=tmp_path)

        skill_dir = tmp_path / ".github" / "skills" / "wfrunner-planner"
        assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == "planner skill\n"
        assert (skill_dir / "references" / "plan-format.md").read_text(encoding="utf-8") == "plan format\n"

    def test_init_does_not_overwrite_existing_planner_skill(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        skill_dir = tmp_path / ".github" / "skills" / "wfrunner-planner"
        skill_dir.mkdir(parents=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("custom planner", encoding="utf-8")

        init(target_dir=tmp_path)

        assert skill_file.read_text(encoding="utf-8") == "custom planner"


class TestInitReturnsZero:

    def test_init_returns_zero(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        assert init(target_dir=tmp_path) == 0


class TestInitCliIntegration:

    def test_init_cli_integration(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)
        result = main(["init"])
        assert result == 0
        assert (tmp_path / ".wfrunner" / "wfrunner.toml").exists()
        assert (tmp_path / ".wfrunner" / "prompts" / "system_prompt.implementation.md").exists()
        assert (tmp_path / ".github" / "agents" / "default.wfrunner.agent.md").exists()

    def test_init_smoke_bootstraps_customer_project_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)

        assert main(["init"]) == 0

        assert (tmp_path / ".wfrunner" / "wfrunner.toml").is_file()
        assert (tmp_path / ".wfrunner" / "prompts" / "system_prompt.implementation.md").is_file()
        assert (tmp_path / ".github" / "agents" / "default.wfrunner.agent.md").is_file()
        assert "# >>> WaterfallRunner managed >>>" in (tmp_path / ".gitignore").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# STEP-007 — TOML template contains all required keys
# ---------------------------------------------------------------------------


class TestInitTomlTemplateKeys:
    """TOML template written by wfrunner init must contain all required keys."""

    def test_toml_template_has_required_keys(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        init(target_dir=tmp_path)
        config_path = tmp_path / ".wfrunner" / "wfrunner.toml"
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))

        assert data["default_model"] == "gpt-5.5"
        assert data["automation_dir"] == ".wfrunner/automation"
        assert data["copilot_command"] == "copilot"
        assert data["default_agent"] == "default.wfrunner"
        assert data["git"]["push_required"] is True
        assert set(data["protected_paths"]["paths"]) == {
            "schemas/",
            "tools/validate_plan.py",
            "tools/run_plan.py",
            ".github/agents/",
            ".github/copilot-instructions.md",
            "prompts/",
            ".wfrunner/wfrunner.toml",
        }


class TestInitRetiresLegacyScaffolding:
    """init no longer scaffolds the retired template or spec-implementer agent."""

    def test_init_does_not_scaffold_implement_step_template(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        init(target_dir=tmp_path)
        assert not (tmp_path / ".wfrunner" / "prompts" / "implement-step.md").exists()

    def test_init_does_not_scaffold_spec_implementer_agent(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        init(target_dir=tmp_path)
        assert not (tmp_path / ".github" / "agents" / "spec-implementer.agent.md").exists()


class TestInitTomlTemplateMatchesDefaults:
    """The generated wfrunner.toml is rendered from the shared DEFAULT_CONFIG."""

    def test_generated_config_matches_default_config(self, tmp_path: Path) -> None:
        from tools.config import DEFAULT_CONFIG

        (tmp_path / ".git").mkdir()
        init(target_dir=tmp_path)
        config_path = tmp_path / ".wfrunner" / "wfrunner.toml"
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))

        assert data["default_model"] == DEFAULT_CONFIG["default_model"]
        assert data["automation_dir"] == DEFAULT_CONFIG["automation_dir"]
        assert data["copilot_command"] == DEFAULT_CONFIG["copilot_command"]
        assert data["default_agent"] == DEFAULT_CONFIG["default_agent"]
        assert data["git_timeout_seconds"] == DEFAULT_CONFIG["git_timeout_seconds"]
        assert data["git_push_timeout_seconds"] == DEFAULT_CONFIG["git_push_timeout_seconds"]
        assert data["pre_analysis_timeout_seconds"] == DEFAULT_CONFIG["pre_analysis_timeout_seconds"]
        assert data["git"]["push_required"] == DEFAULT_CONFIG["git"]["push_required"]


class TestInitScaffoldsReviewFixAgents:
    """init scaffolds the optional codereview and codefix agents."""

    def test_init_scaffolds_codereview_and_codefix_agents(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        init(target_dir=tmp_path)
        agents_dir = tmp_path / ".github" / "agents"
        assert (agents_dir / "codereview.agent.md").stat().st_size > 0
        assert (agents_dir / "codefix.agent.md").stat().st_size > 0

    def test_init_gitignore_lists_review_fix_agents(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        init(target_dir=tmp_path)
        gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        assert ".github/agents/codereview.agent.md" in gitignore
        assert ".github/agents/codefix.agent.md" in gitignore

