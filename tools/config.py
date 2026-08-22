"""Configuration loading for WaterfallRunner."""

from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass, field
from pathlib import Path
import tomllib
from typing import Any

import jsonschema

from tools.constants import AGENT_DEFAULT, MODEL_DEFAULT
from tools.data_path import require_runtime_resource


class ConfigNotFoundError(Exception):
    """Raised when no TOML configuration file can be found."""


# ---------------------------------------------------------------------------
# Security floor constants (additive-only, not user-overridable defaults)
# ---------------------------------------------------------------------------

BUILTIN_DENY_TOOLS: tuple[str, ...] = (
    "shell(rm)",
    "shell(git push)",
    "shell(git reset)",
    "shell(git clean)",
    "shell(git commit)",
)

BUILTIN_ALLOW_TOOLS: tuple[str, ...] = (
    "write",
    "shell(python)",
    "shell(pip)",
    "shell(git)",
)

BUILTIN_PROTECTED_PATHS: tuple[str, ...] = (
    "schemas/",
    "tools/validate_plan.py",
    "tools/run_plan.py",
    ".github/agents/",
    ".github/copilot-instructions.md",
    "prompts/",
    ".wfrunner/wfrunner.toml",
)


# ---------------------------------------------------------------------------
# Default configuration values (single source of truth)
# ---------------------------------------------------------------------------
#
# These defaults back both the layered loader (load_config) and the config
# template written by `wfrunner init`. Keep this the only place that names a
# default value so the generated wfrunner.toml can never drift from the
# loader's fallbacks.

DEFAULT_CONFIG: dict[str, Any] = {
    "default_model": "gpt-5.5",
    "automation_dir": ".wfrunner/automation",
    "copilot_command": "copilot",
    "default_agent": "default.wfrunner",
    "git_timeout_seconds": 30,
    "git_push_timeout_seconds": 60,
    "pre_analysis_timeout_seconds": 300,
    "copilot_cli": {
        "timeout_seconds": 600,
    },
    "git": {
        "push_required": True,
    },
}


@dataclass(frozen=True)
class CopilotCliConfig:
    """Copilot CLI tool permissions and timeout configuration."""

    timeout_seconds: int
    allow_tools: tuple[str, ...]
    deny_tools: tuple[str, ...]


@dataclass(frozen=True)
class GitConfig:
    """Git configuration for automated commits."""

    push_required: bool


@dataclass(frozen=True)
class ConfigLayer:
    """Values contributed by one configuration source."""

    values: dict[str, Any] = field(default_factory=dict)
    copilot_cli: dict[str, Any] = field(default_factory=dict)
    git: dict[str, Any] = field(default_factory=dict)
    deny_tools: frozenset[str] = frozenset()
    protected_paths: frozenset[str] = frozenset()


@dataclass(frozen=True)
class WaterfallRunnerConfig:
    """WaterfallRunner configuration values."""

    default_model: str
    automation_dir: str
    copilot_command: str
    default_agent: str
    copilot_cli: CopilotCliConfig
    protected_paths: tuple[str, ...]
    git: GitConfig
    git_timeout_seconds: int
    git_push_timeout_seconds: int
    pre_analysis_timeout_seconds: int

    def resolve_model(self, step_model: str) -> str:
        """Resolve a step's model field against the configured default.

        A step may set ``model: default`` (the sentinel) to defer to
        ``default_model``. The returned value can itself still be the sentinel
        when ``default_model`` is left unset, in which case the caller should
        omit model selection and let the agent CLI choose its own default.
        """
        return self.default_model if step_model == MODEL_DEFAULT else step_model

    def resolve_agent(self, step_agent: str) -> str:
        """Resolve a step's agent field against the configured default."""
        return self.default_agent if step_agent == AGENT_DEFAULT else step_agent


def user_config_path() -> Path:
    """Return the user-scope config file path.

    Windows: %APPDATA%\\WaterfallRunner\\config.toml
    Linux/macOS: ~/.config/wfrunner/config.toml
    """
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return Path(appdata) / "WaterfallRunner" / "config.toml"
    return Path.home() / ".config" / "wfrunner" / "config.toml"


def load_config(
    project_root: Path | None = None,
    cli_overrides: dict | None = None,
    config_file: Path | None = None,
) -> WaterfallRunnerConfig:
    """Load WaterfallRunner configuration with layered merging.

    Merge order: built-in defaults -> user config -> project config -> CLI overrides.
    For deny_tools and protected_paths, merging is additive (set union).
    When config_file is supplied, load exactly that TOML file instead of user/project layers.

    Raises:
        ConfigNotFoundError: If no TOML config source is found.
    """
    layers = [
        ConfigLayer(
            values={
                key: value
                for key, value in DEFAULT_CONFIG.items()
                if not isinstance(value, dict)
            },
            deny_tools=frozenset(BUILTIN_DENY_TOOLS),
            protected_paths=frozenset(BUILTIN_PROTECTED_PATHS),
        )
    ]
    has_config_source = False

    if config_file is not None:
        explicit_path = Path(config_file)
        if not explicit_path.exists():
            raise ConfigNotFoundError(f"Config file not found: {explicit_path}")
        layers.append(_load_toml_layer(explicit_path))
        has_config_source = True
    else:
        # Layer 2: user config
        user_path = user_config_path()
        if user_path.exists():
            layers.append(_load_toml_layer(user_path))
            has_config_source = True

        # Layer 3: project config
        root = Path.cwd() if project_root is None else Path(project_root)
        project_path = root / ".wfrunner" / "wfrunner.toml"
        if project_path.exists():
            layers.append(_load_toml_layer(project_path))
            has_config_source = True

    # Layer 4: CLI overrides
    if cli_overrides:
        override_values: dict[str, Any] = {}
        for key in ("default_model", "automation_dir", "copilot_command", "default_agent"):
            if key in cli_overrides:
                override_values[key] = _require_string(key, cli_overrides[key])
        if override_values:
            layers.append(ConfigLayer(values=override_values))
            has_config_source = True

    if not has_config_source:
        raise ConfigNotFoundError(
            "No configuration found. Run 'wfrunner init' to create "
            ".wfrunner/wfrunner.toml, or pass --config."
        )

    merged = ConfigLayer()
    for layer in layers:
        merged = _merge_config_layers(merged, layer)

    values = dict(merged.values)
    # Build final copilot_cli config
    final_deny_tools = tuple(sorted(merged.deny_tools))
    default_cli_timeout = DEFAULT_CONFIG["copilot_cli"]["timeout_seconds"]
    if merged.copilot_cli:
        values["copilot_cli"] = CopilotCliConfig(
            timeout_seconds=merged.copilot_cli.get("timeout_seconds", default_cli_timeout),
            allow_tools=merged.copilot_cli.get("allow_tools", BUILTIN_ALLOW_TOOLS),
            deny_tools=final_deny_tools,
        )
    else:
        values["copilot_cli"] = CopilotCliConfig(
            timeout_seconds=default_cli_timeout,
            allow_tools=BUILTIN_ALLOW_TOOLS,
            deny_tools=final_deny_tools,
        )

    values["protected_paths"] = tuple(sorted(merged.protected_paths))

    values["git"] = GitConfig(
        push_required=merged.git.get("push_required", DEFAULT_CONFIG["git"]["push_required"]),
    )

    return WaterfallRunnerConfig(**values)


def _merge_config_layers(base: ConfigLayer, override: ConfigLayer) -> ConfigLayer:
    """Merge one config layer over another while preserving security floors."""
    return ConfigLayer(
        values=base.values | override.values,
        copilot_cli=base.copilot_cli | override.copilot_cli,
        git=base.git | override.git,
        deny_tools=base.deny_tools | override.deny_tools,
        protected_paths=base.protected_paths | override.protected_paths,
    )


def _load_toml_layer(config_path: Path) -> ConfigLayer:
    """Load and validate the values contributed by one TOML file."""
    with config_path.open("rb") as f:
        data = tomllib.load(f)
    _validate_config_schema(config_path, data)

    values: dict[str, Any] = {}
    cli_config_values: dict[str, Any] = {}
    git_values: dict[str, Any] = {}
    deny_tools: frozenset[str] = frozenset()
    protected_paths: frozenset[str] = frozenset()

    for key in ("default_model", "automation_dir", "copilot_command", "default_agent"):
        if key in data:
            values[key] = _require_string(key, data[key])

    for timeout_key in ("git_timeout_seconds", "git_push_timeout_seconds", "pre_analysis_timeout_seconds"):
        if timeout_key in data:
            tv = data[timeout_key]
            if not isinstance(tv, int):
                raise ValueError(f"{config_path}: {timeout_key} must be an int")
            values[timeout_key] = tv

    cli_section = data.get("copilot_cli")
    if cli_section is not None and isinstance(cli_section, dict):
        if "timeout_seconds" in cli_section:
            timeout = cli_section["timeout_seconds"]
            if not isinstance(timeout, int):
                raise ValueError(f"{config_path}: timeout_seconds must be an int")
            cli_config_values["timeout_seconds"] = timeout

        for tools_key in ("allow_tools", "deny_tools"):
            if tools_key in cli_section:
                tools_val = cli_section[tools_key]
                if isinstance(tools_val, list):
                    if not all(isinstance(t, str) for t in tools_val):
                        raise ValueError(f"{config_path}: {tools_key} must be a list of strings")
                    if tools_key == "deny_tools":
                        deny_tools = frozenset(tools_val)
                    else:
                        cli_config_values[tools_key] = tuple(tools_val)
                else:
                    raise ValueError(f"{config_path}: {tools_key} must be a list of strings")

    pp_section = data.get("protected_paths")
    if pp_section is not None and isinstance(pp_section, dict):
        paths_val = pp_section.get("paths")
        if paths_val is not None:
            if isinstance(paths_val, list):
                if not all(isinstance(p, str) for p in paths_val):
                    raise ValueError(f"{config_path}: paths must be a list of strings")
                protected_paths = frozenset(paths_val)
            else:
                raise ValueError(f"{config_path}: paths must be a list of strings")

    git_section = data.get("git")
    if git_section is not None and isinstance(git_section, dict):
        for bool_key in ("push_required",):
            if bool_key in git_section:
                bool_val = git_section[bool_key]
                if not isinstance(bool_val, bool):
                    raise ValueError(f"{config_path}: {bool_key} must be a bool")
                git_values[bool_key] = bool_val

    return ConfigLayer(
        values=values,
        copilot_cli=cli_config_values,
        git=git_values,
        deny_tools=deny_tools,
        protected_paths=protected_paths,
    )


def _require_string(key: str, value: Any) -> str:
    """Validate that a supported configuration value is a string."""
    if not isinstance(value, str):
        raise ValueError(f"wfrunner.toml: {key} must be a string")
    return value


def _validate_config_schema(config_path: Path, data: dict[str, Any]) -> None:
    schema_path = require_runtime_resource(
        Path("schemas") / "config.schema.json",
        description="config schema",
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        path_parts = [str(part) for part in error.path]
        path = ".".join(path_parts)
        if path_parts and path_parts[-1].isdigit() and len(path_parts) >= 2:
            field_name = path_parts[-2]
        else:
            field_name = path_parts[-1] if path_parts else "config"
        if field_name in {"allow_tools", "deny_tools", "paths"}:
            detail = f"{field_name} must be a list of strings"
        else:
            detail = error.message
        location = f"{path}: " if path else ""
        raise ValueError(f"{config_path}: config validation failed: {location}{detail}")
