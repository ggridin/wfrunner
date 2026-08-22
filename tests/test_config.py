"""Tests for WaterfallRunner configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.config import (
    BUILTIN_ALLOW_TOOLS,
    BUILTIN_DENY_TOOLS,
    CopilotCliConfig,
    ConfigNotFoundError,
    GitConfig,
    WaterfallRunnerConfig,
    load_config,
)


def _write_wfrunner_toml(project_root: Path, content: str) -> None:
    wfrunner_dir = project_root / ".wfrunner"
    wfrunner_dir.mkdir(parents=True, exist_ok=True)
    (wfrunner_dir / "wfrunner.toml").write_text(content, encoding="utf-8")


EXPECTED_BUILTIN_PROTECTED_PATHS = {
    "schemas/",
    "tools/validate_plan.py",
    "tools/run_plan.py",
    ".github/agents/",
    ".github/copilot-instructions.md",
    "prompts/",
    ".wfrunner/wfrunner.toml",
}


class TestConfigDefaults:
    """Verify default configuration via load_config with minimal TOML."""

    def test_default_config_values(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(tmp_path, 'default_model = "default"\n')
        config = load_config(tmp_path)

        assert config.default_model == "default"
        assert config.automation_dir == ".wfrunner/automation"
        assert config.copilot_command == "copilot"
        assert config.default_agent == "default.wfrunner"

    def test_defaults_when_wfrunner_toml_does_not_exist_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("tools.config.user_config_path", lambda: tmp_path / "nonexistent.toml")
        (tmp_path / ".wfrunner").mkdir()

        with pytest.raises(ConfigNotFoundError):
            load_config(tmp_path)

    def test_defaults_when_wfrunner_dir_does_not_exist_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("tools.config.user_config_path", lambda: tmp_path / "nonexistent.toml")

        with pytest.raises(ConfigNotFoundError):
            load_config(tmp_path)


class TestResolveModel:
    """Verify WaterfallRunnerConfig.resolve_model against the default sentinel."""

    def test_step_model_overrides_default(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(tmp_path, 'default_model = "config-model"\n')
        config = load_config(tmp_path)

        assert config.resolve_model("step-model") == "step-model"

    def test_sentinel_resolves_to_configured_default(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(tmp_path, 'default_model = "config-model"\n')
        config = load_config(tmp_path)

        assert config.resolve_model("default") == "config-model"

    def test_sentinel_stays_when_default_is_also_sentinel(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(tmp_path, 'default_model = "default"\n')
        config = load_config(tmp_path)

        assert config.resolve_model("default") == "default"


class TestResolveAgent:
    """Verify WaterfallRunnerConfig.resolve_agent against the default sentinel."""

    def test_step_agent_overrides_default(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(tmp_path, 'default_agent = "config-agent"\n')
        config = load_config(tmp_path)

        assert config.resolve_agent("step-agent") == "step-agent"

    def test_sentinel_resolves_to_configured_default(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(tmp_path, 'default_agent = "config-agent"\n')
        config = load_config(tmp_path)

        assert config.resolve_agent("default") == "config-agent"

    def test_sentinel_resolution_honors_custom_default_agent(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(tmp_path, 'default_agent = "custom-agent"\n')
        config = load_config(tmp_path)

        assert config.resolve_agent("default") == "custom-agent"


class TestConfigLoading:
    """Verify wfrunner.toml loading behavior."""

    def test_loads_exact_explicit_config_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("tools.config.user_config_path", lambda: tmp_path / "missing-user.toml")
        explicit_dir = tmp_path / "configs"
        explicit_dir.mkdir()
        explicit_config = explicit_dir / "chosen.toml"
        explicit_config.write_text('default_model = "explicit-model"\n', encoding="utf-8")
        _write_wfrunner_toml(explicit_dir, 'default_model = "nested-project-model"\n')

        config = load_config(config_file=explicit_config)

        assert config.default_model == "explicit-model"

    def test_missing_explicit_config_file_raises_config_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigNotFoundError):
            load_config(config_file=tmp_path / "missing.toml")

    def test_unrecognized_config_path_override_does_not_count_as_config_layer(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("tools.config.user_config_path", lambda: tmp_path / "missing-user.toml")

        with pytest.raises(ConfigNotFoundError):
            load_config(tmp_path, cli_overrides={"_config_path": "ignored.toml"})

    def test_loads_supported_keys_from_wfrunner_section(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(
            tmp_path,
            """
default_model = "gpt-5-mini"
automation_dir = "build/automation"
copilot_command = "gh-copilot"
default_agent = "custom-implementer"
""".lstrip(),
        )

        config = load_config(tmp_path)

        assert config.default_model == "gpt-5-mini"
        assert config.automation_dir == "build/automation"
        assert config.copilot_command == "gh-copilot"
        assert config.default_agent == "custom-implementer"

    def test_missing_supported_keys_fall_back_to_defaults(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(
            tmp_path,
            """
default_model = "gpt-5-mini"
""".lstrip(),
        )

        config = load_config(tmp_path)

        assert config.default_model == "gpt-5-mini"
        assert config.automation_dir == ".wfrunner/automation"
        assert config.copilot_command == "copilot"
        assert config.default_agent == "default.wfrunner"

    def test_unknown_keys_are_ignored(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(
            tmp_path,
            """
default_model = "gpt-5-mini"
future_option = true
nested = { value = "ignored" }
""".lstrip(),
        )

        config = load_config(tmp_path)

        assert config.default_model == "gpt-5-mini"
        assert not hasattr(config, "future_option")
        assert not hasattr(config, "nested")

    def test_load_config_reads_wfrunner_toml_from_given_directory(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        other_root = tmp_path / "other"
        project_root.mkdir()
        other_root.mkdir()
        _write_wfrunner_toml(
            project_root,
            """
default_model = "configured-model"
""".lstrip(),
        )
        _write_wfrunner_toml(
            other_root,
            """
default_model = "other-model"
""".lstrip(),
        )

        config = load_config(project_root)

        assert config.default_model == "configured-model"


class TestConfigValidation:
    """Verify invalid configuration is rejected clearly."""

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("default_model", "123"),
            ("automation_dir", "[\".wfrunner/automation\"]"),
            ("copilot_command", "true"),
            ("default_agent", "{ name = \"agent\" }"),
        ],
    )
    def test_invalid_supported_key_type_raises_clear_error(
        self,
        tmp_path: Path,
        key: str,
        value: str,
    ) -> None:
        _write_wfrunner_toml(
            tmp_path,
            f"""
{key} = {value}
""".lstrip(),
        )

        with pytest.raises(ValueError, match=rf"{key}.*string"):
            load_config(tmp_path)


class TestCopilotCliConfig:
    """Verify CopilotCliConfig defaults and [copilot_cli] loading."""

    def test_default_copilot_cli_config_values(self) -> None:
        cli = CopilotCliConfig(
            timeout_seconds=600,
            allow_tools=BUILTIN_ALLOW_TOOLS,
            deny_tools=BUILTIN_DENY_TOOLS,
        )

        assert cli.timeout_seconds == 600
        assert cli.allow_tools == (
            "write",
            "shell(python)",
            "shell(pip)",
            "shell(git)",
        )
        assert cli.deny_tools == (
            "shell(rm)",
            "shell(git push)",
            "shell(git reset)",
            "shell(git clean)",
            "shell(git commit)",
        )

    def test_copilot_cli_defaults_when_section_absent(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(tmp_path, 'default_model = "gpt-4"\n')

        config = load_config(tmp_path)

        assert config.copilot_cli.timeout_seconds == 600
        assert config.copilot_cli.allow_tools == BUILTIN_ALLOW_TOOLS
        assert set(config.copilot_cli.deny_tools) == set(BUILTIN_DENY_TOOLS)

    def test_loads_copilot_cli_section(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(
            tmp_path,
            """
[copilot_cli]
timeout_seconds = 120
allow_tools = ["write", "shell(node)"]
deny_tools = ["shell(rm)"]
""".lstrip(),
        )

        config = load_config(tmp_path)

        assert config.copilot_cli.timeout_seconds == 120
        assert config.copilot_cli.allow_tools == ("write", "shell(node)")
        # deny_tools includes built-in floor via additive merge
        assert "shell(rm)" in config.copilot_cli.deny_tools
        for builtin in BUILTIN_DENY_TOOLS:
            assert builtin in config.copilot_cli.deny_tools

    def test_partial_copilot_cli_falls_back_to_defaults(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(
            tmp_path,
            """
[copilot_cli]
timeout_seconds = 300
""".lstrip(),
        )

        config = load_config(tmp_path)

        assert config.copilot_cli.timeout_seconds == 300
        assert config.copilot_cli.allow_tools == BUILTIN_ALLOW_TOOLS
        assert set(config.copilot_cli.deny_tools) == set(BUILTIN_DENY_TOOLS)

    def test_copilot_cli_timeout_must_be_int(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(
            tmp_path,
            """
[copilot_cli]
timeout_seconds = "fast"
""".lstrip(),
        )

        with pytest.raises(ValueError, match=r"timeout_seconds.*int"):
            load_config(tmp_path)

    def test_copilot_cli_allow_tools_must_be_list_of_strings(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(
            tmp_path,
            """
[copilot_cli]
allow_tools = "write"
""".lstrip(),
        )

        with pytest.raises(ValueError, match=r"allow_tools.*list.*string"):
            load_config(tmp_path)

    def test_copilot_cli_deny_tools_must_be_list_of_strings(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(
            tmp_path,
            """
[copilot_cli]
deny_tools = 42
""".lstrip(),
        )

        with pytest.raises(ValueError, match=r"deny_tools.*list.*string"):
            load_config(tmp_path)


class TestProtectedPathsConfig:
    """Verify protected_paths defaults and [protected_paths] loading."""

    def test_protected_paths_include_builtin_floor_when_section_absent(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("tools.config.user_config_path", lambda: tmp_path / "nonexistent.toml")
        _write_wfrunner_toml(tmp_path, 'default_model = "default"\n')
        config = load_config(tmp_path)

        assert set(config.protected_paths) == EXPECTED_BUILTIN_PROTECTED_PATHS

    def test_loads_custom_protected_paths_additively_with_builtin_floor(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("tools.config.user_config_path", lambda: tmp_path / "nonexistent.toml")
        _write_wfrunner_toml(
            tmp_path,
            """
[protected_paths]
paths = ["custom/", "special.txt"]
""".lstrip(),
        )

        config = load_config(tmp_path)

        assert set(config.protected_paths) == EXPECTED_BUILTIN_PROTECTED_PATHS | {"custom/", "special.txt"}

    def test_empty_project_protected_paths_cannot_remove_builtin_floor(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("tools.config.user_config_path", lambda: tmp_path / "nonexistent.toml")
        _write_wfrunner_toml(
            tmp_path,
            """
[protected_paths]
paths = []
""".lstrip(),
        )

        config = load_config(tmp_path)

        assert set(config.protected_paths) == EXPECTED_BUILTIN_PROTECTED_PATHS

    def test_protected_paths_must_be_list_of_strings(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(
            tmp_path,
            """
[protected_paths]
paths = 42
""".lstrip(),
        )

        with pytest.raises(ValueError, match=r"paths.*list.*string"):
            load_config(tmp_path)

    def test_protected_paths_elements_must_be_strings(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(
            tmp_path,
            """
[protected_paths]
paths = ["ok", 123]
""".lstrip(),
        )

        with pytest.raises(ValueError, match=r"paths.*list.*string"):
            load_config(tmp_path)


class TestGitConfig:
    """Verify GitConfig defaults and [git] section loading."""

    def test_default_git_config_values(self) -> None:
        git = GitConfig(push_required=True)
        assert git.push_required is True

    def test_git_defaults_when_section_absent(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(tmp_path, 'default_model = "gpt-4"\n')

        config = load_config(tmp_path)

        assert config.git.push_required is True

    def test_loads_git_push_required_false(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(
            tmp_path,
            """
[git]
push_required = false
""".lstrip(),
        )

        config = load_config(tmp_path)

        assert config.git.push_required is False

    def test_loads_git_push_required_true(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(
            tmp_path,
            """
[git]
push_required = true
""".lstrip(),
        )

        config = load_config(tmp_path)

        assert config.git.push_required is True

    def test_git_push_required_must_be_bool(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(
            tmp_path,
            """
[git]
push_required = "yes"
""".lstrip(),
        )

        with pytest.raises(ValueError, match=r"push_required.*bool"):
            load_config(tmp_path)


class TestLayeredConfigLoading:
    """Verify layered config merging: built-in -> user -> project -> CLI."""

    def _write_user_config(self, user_config_path: Path, content: str) -> None:
        user_config_path.parent.mkdir(parents=True, exist_ok=True)
        user_config_path.write_text(content, encoding="utf-8")

    def test_user_config_provides_defaults(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        user_path = tmp_path / "user_config" / "config.toml"
        self._write_user_config(user_path, 'default_model = "user-model"\n')
        monkeypatch.setattr("tools.config.user_config_path", lambda: user_path)

        # No project config
        project_root = tmp_path / "project"
        project_root.mkdir()
        config = load_config(project_root)

        assert config.default_model == "user-model"

    def test_project_config_overrides_user_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        user_path = tmp_path / "user_config" / "config.toml"
        self._write_user_config(user_path, 'default_model = "user-model"\n')
        monkeypatch.setattr("tools.config.user_config_path", lambda: user_path)

        project_root = tmp_path / "project"
        _write_wfrunner_toml(project_root, 'default_model = "project-model"\n')
        config = load_config(project_root)

        assert config.default_model == "project-model"

    def test_cli_overrides_all(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        user_path = tmp_path / "user_config" / "config.toml"
        self._write_user_config(user_path, 'default_model = "user-model"\n')
        monkeypatch.setattr("tools.config.user_config_path", lambda: user_path)

        project_root = tmp_path / "project"
        _write_wfrunner_toml(project_root, 'default_model = "project-model"\n')
        config = load_config(project_root, cli_overrides={"default_model": "cli-model"})

        assert config.default_model == "cli-model"

    def test_deny_tools_cannot_loosen_builtin_floor(self, tmp_path: Path) -> None:
        # Project config with fewer deny_tools than built-in
        _write_wfrunner_toml(
            tmp_path,
            """
[copilot_cli]
deny_tools = ["shell(rm)"]
""".lstrip(),
        )
        config = load_config(tmp_path)

        builtin_deny = set(BUILTIN_DENY_TOOLS)
        assert builtin_deny.issubset(set(config.copilot_cli.deny_tools))

    def test_project_protected_paths_are_additive_with_builtin_floor(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("tools.config.user_config_path", lambda: tmp_path / "nonexistent.toml")
        _write_wfrunner_toml(
            tmp_path,
            """
[protected_paths]
paths = ["custom/"]
""".lstrip(),
        )
        config = load_config(tmp_path)

        assert set(config.protected_paths) == EXPECTED_BUILTIN_PROTECTED_PATHS | {"custom/"}

    def test_deny_tools_can_be_tightened(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(
            tmp_path,
            """
[copilot_cli]
deny_tools = ["shell(curl)", "shell(wget)"]
""".lstrip(),
        )
        config = load_config(tmp_path)

        assert "shell(curl)" in config.copilot_cli.deny_tools
        assert "shell(wget)" in config.copilot_cli.deny_tools
        # Built-in floor is still present
        for builtin in BUILTIN_DENY_TOOLS:
            assert builtin in config.copilot_cli.deny_tools

    def test_project_layer_cannot_remove_user_security_restrictions(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user_path = tmp_path / "user_config" / "config.toml"
        self._write_user_config(
            user_path,
            """
[copilot_cli]
deny_tools = ["shell(user-only)"]

[protected_paths]
paths = ["user-protected/"]
""".lstrip(),
        )
        monkeypatch.setattr("tools.config.user_config_path", lambda: user_path)
        _write_wfrunner_toml(
            tmp_path,
            """
[copilot_cli]
deny_tools = ["shell(project-only)"]

[protected_paths]
paths = ["project-protected/"]
""".lstrip(),
        )

        config = load_config(tmp_path)

        assert set(config.copilot_cli.deny_tools) == set(BUILTIN_DENY_TOOLS) | {
            "shell(user-only)",
            "shell(project-only)",
        }
        assert set(config.protected_paths) == EXPECTED_BUILTIN_PROTECTED_PATHS | {
            "user-protected/",
            "project-protected/",
        }


# ---------------------------------------------------------------------------
# STEP-007 — Config no-defaults and ConfigNotFoundError tests
# ---------------------------------------------------------------------------


class TestConfigNoDefaults:
    """WaterfallRunnerConfig() with no arguments must raise TypeError after refactor."""

    def test_no_args_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            WaterfallRunnerConfig()


class TestConfigNotFoundError:
    """load_config() must raise ConfigNotFoundError when no TOML exists."""

    def test_load_config_raises_when_no_toml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Ensure no user config either
        monkeypatch.setattr("tools.config.user_config_path", lambda: tmp_path / "nonexistent.toml")
        with pytest.raises(ConfigNotFoundError):
            load_config(tmp_path)

    def test_load_config_with_valid_toml_returns_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("tools.config.user_config_path", lambda: tmp_path / "nonexistent.toml")
        _write_wfrunner_toml(
            tmp_path,
            """
default_model = "gpt-4"
automation_dir = ".wfrunner/automation"
copilot_command = "copilot"
default_agent = "default.wfrunner"
""".lstrip(),
        )
        config = load_config(tmp_path)
        assert config.default_model == "gpt-4"
        assert config.automation_dir == ".wfrunner/automation"

    def test_deny_tools_floor_enforced_with_valid_toml(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("tools.config.user_config_path", lambda: tmp_path / "nonexistent.toml")
        _write_wfrunner_toml(
            tmp_path,
            """
default_model = "gpt-4"
automation_dir = ".wfrunner/automation"
copilot_command = "copilot"
default_agent = "default.wfrunner"

[copilot_cli]
deny_tools = []
""".lstrip(),
        )
        config = load_config(tmp_path)
        # Built-in deny_tools floor is always enforced
        for tool in ("shell(rm)", "shell(git push)", "shell(git reset)", "shell(git clean)", "shell(git commit)"):
            assert tool in config.copilot_cli.deny_tools
        assert set(config.protected_paths) == EXPECTED_BUILTIN_PROTECTED_PATHS


# ---------------------------------------------------------------------------
# Timeout configuration (STEP-031 RED tests)
# ---------------------------------------------------------------------------


class TestTimeoutConfig:
    """Verify timeout fields are loaded from TOML into WaterfallRunnerConfig."""

    def test_git_timeout_seconds_loaded_from_toml(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(
            tmp_path,
            """
default_model = "gpt-4"
git_timeout_seconds = 45
""".lstrip(),
        )
        config = load_config(tmp_path)
        assert config.git_timeout_seconds == 45

    def test_git_push_timeout_seconds_loaded_from_toml(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(
            tmp_path,
            """
default_model = "gpt-4"
git_push_timeout_seconds = 120
""".lstrip(),
        )
        config = load_config(tmp_path)
        assert config.git_push_timeout_seconds == 120

    def test_pre_analysis_timeout_seconds_loaded_from_toml(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(
            tmp_path,
            """
default_model = "gpt-4"
pre_analysis_timeout_seconds = 600
""".lstrip(),
        )
        config = load_config(tmp_path)
        assert config.pre_analysis_timeout_seconds == 600

    def test_missing_timeout_keys_use_sensible_defaults(self, tmp_path: Path) -> None:
        _write_wfrunner_toml(
            tmp_path,
            """
default_model = "gpt-4"
""".lstrip(),
        )
        config = load_config(tmp_path)
        assert config.git_timeout_seconds == 30
        assert config.git_push_timeout_seconds == 60
        assert config.pre_analysis_timeout_seconds == 300