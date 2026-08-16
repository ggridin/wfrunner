"""Tests for the Copilot CLI agent adapter."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from tests.helpers import make_default_config
from tools.config import BUILTIN_ALLOW_TOOLS, BUILTIN_DENY_TOOLS, CopilotCliConfig
from tools.orchestrator.agent_adapter import AgentAdapter, AgentInvocationRequest
from tools.orchestrator.copilot_cli_adapter import CopilotCliAdapter


def _write_system_prompt(tmp_path: Path, content: str | None = None) -> Path:
    system_prompt = tmp_path / "prompts" / "system_prompt.implementation.md"
    system_prompt.parent.mkdir(parents=True, exist_ok=True)
    system_prompt.write_text(
        content or "Execute exactly one bounded step and modify only allowed files.\n",
        encoding="utf-8",
    )
    return system_prompt


def _make_request(tmp_path: Path, model: str = "gpt-4.1") -> AgentInvocationRequest:
    request = AgentInvocationRequest(
        step_id="STEP-015",
        agent_name="default.wfrunner",
        model=model,
        system_prompt_path=str(_write_system_prompt(tmp_path)),
        step_prompt="Write tests for the Copilot CLI agent adapter.",
        plan_context="WaterfallRunner orchestrates AI-assisted implementation.",
        allowed_files=[
            "tests/test_copilot_cli_adapter.py",
            "tools/orchestrator/copilot_cli_adapter.py",
        ],
        verification_commands=[
            "python -m pytest tests/test_copilot_cli_adapter.py --co -q",
        ],
    )
    request.title = "Write tests for Copilot CLI agent adapter"
    return request


def _invoke_and_get_command(
    adapter: CopilotCliAdapter,
    request: AgentInvocationRequest,
) -> list[str]:
    with patch("tools.orchestrator.copilot_cli_adapter.subprocess.run") as run_mock:
        run_mock.return_value = _completed_process()

        adapter.invoke(request)

    return run_mock.call_args.args[0]


def _option_value(command: list[str], option: str) -> str:
    option_index = command.index(option)
    return command[option_index + 1]


def _completed_process(returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["copilot"],
        returncode=returncode,
        stdout="agent output",
        stderr="agent error",
    )


class TestCopilotCliAdapterContract:
    """Verify the adapter conforms to the orchestrator contract."""

    def test_extends_agent_adapter(self, tmp_path: Path) -> None:
        adapter = CopilotCliAdapter(make_default_config(), tmp_path / ".automation")

        assert issubclass(CopilotCliAdapter, AgentAdapter)
        assert isinstance(adapter, AgentAdapter)


class TestCopilotCliAdapterCommand:
    """Verify Copilot CLI command construction and prompt rendering."""

    def test_builds_copilot_command_from_request(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path, model="gpt-4.1")
        adapter = CopilotCliAdapter(make_default_config(), tmp_path / ".automation")

        with patch("tools.orchestrator.copilot_cli_adapter.subprocess.run") as run_mock:
            run_mock.return_value = _completed_process()

            adapter.invoke(request)

        command = run_mock.call_args.args[0]
        assert command == [
            "copilot",
            "--agent",
            "default.wfrunner",
            "-p",
            command[4],
            "--model",
            "gpt-4.1",
            "--allow-tool=write",
            "--allow-tool=shell(python)",
            "--allow-tool=shell(pip)",
            "--allow-tool=shell(git)",
            "--deny-tool=shell(rm)",
            "--deny-tool=shell(git push)",
            "--deny-tool=shell(git reset)",
            "--deny-tool=shell(git clean)",
            "--deny-tool=shell(git commit)",
        ]
        assert run_mock.call_args.kwargs["capture_output"] is True
        assert run_mock.call_args.kwargs["text"] is True
        assert run_mock.call_args.kwargs["timeout"] == 600

    def test_tool_permission_flags_do_not_quote_tool_names(
        self,
        tmp_path: Path,
    ) -> None:
        request = _make_request(tmp_path)
        adapter = CopilotCliAdapter(make_default_config(), tmp_path / ".automation")

        command = _invoke_and_get_command(adapter, request)
        tool_permission_args = [
            arg
            for arg in command
            if arg.startswith(("--allow-tool=", "--deny-tool="))
        ]

        assert tool_permission_args == [
            "--allow-tool=write",
            "--allow-tool=shell(python)",
            "--allow-tool=shell(pip)",
            "--allow-tool=shell(git)",
            "--deny-tool=shell(rm)",
            "--deny-tool=shell(git push)",
            "--deny-tool=shell(git reset)",
            "--deny-tool=shell(git clean)",
            "--deny-tool=shell(git commit)",
        ]
        assert all("'" not in arg for arg in tool_permission_args)

    def test_passes_agent_name_and_assembled_message_to_same_invocation(
        self,
        tmp_path: Path,
    ) -> None:
        request = _make_request(tmp_path)
        adapter = CopilotCliAdapter(make_default_config(), tmp_path / ".automation")

        command = _invoke_and_get_command(adapter, request)

        assert _option_value(command, "--agent") == "default.wfrunner"
        assert "STEP-015" in _option_value(command, "-p")

    def test_forwards_different_agent_names_unchanged(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        request.agent_name = "custom-phase-three-agent"
        adapter = CopilotCliAdapter(make_default_config(), tmp_path / ".automation")

        command = _invoke_and_get_command(adapter, request)

        assert _option_value(command, "--agent") == "custom-phase-three-agent"

    def test_resolves_default_agent_from_config(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        request.agent_name = "default"
        config = make_default_config(default_agent="configured-agent")
        adapter = CopilotCliAdapter(config, tmp_path / ".automation")

        command = _invoke_and_get_command(adapter, request)

        assert _option_value(command, "--agent") == "configured-agent"

    def test_uses_configured_copilot_command(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        config = make_default_config(copilot_command="custom-copilot")
        adapter = CopilotCliAdapter(config, tmp_path / ".automation")

        with patch("tools.orchestrator.copilot_cli_adapter.subprocess.run") as run_mock:
            run_mock.return_value = _completed_process()

            adapter.invoke(request)

        assert run_mock.call_args.args[0][0] == "custom-copilot"

    def test_resolves_default_model_from_config(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path, model="default")
        config = make_default_config(default_model="configured-model")
        adapter = CopilotCliAdapter(config, tmp_path / ".automation")

        with patch("tools.orchestrator.copilot_cli_adapter.subprocess.run") as run_mock:
            run_mock.return_value = _completed_process()

            adapter.invoke(request)

        command = run_mock.call_args.args[0]
        assert command[command.index("--model") + 1] == "configured-model"

    def test_omits_model_flag_when_resolved_model_is_default_sentinel(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path, model="default")
        config = make_default_config(default_model="default")
        adapter = CopilotCliAdapter(config, tmp_path / ".automation")

        command = _invoke_and_get_command(adapter, request)

        assert "--model" not in command
    """Verify subprocess outcomes are translated to AgentResult values."""

    def test_successful_invocation_returns_done_result(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        adapter = CopilotCliAdapter(make_default_config(), tmp_path / ".automation")
        stdout = '{"schema_version":1,"step_id":"STEP-015","status":"DONE"}'

        with patch("tools.orchestrator.copilot_cli_adapter.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=["copilot"], returncode=0, stdout=stdout, stderr=""
            )

            result = adapter.invoke(request)

        assert result.schema_version == 1
        assert result.step_id == "STEP-015"
        assert result.status == "DONE"
        assert result.stop_condition_hit is None

    def test_agent_blocked_json_overrides_exit_code_zero(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        adapter = CopilotCliAdapter(make_default_config(), tmp_path / ".automation")
        stdout = 'Some output\n{"schema_version":1,"step_id":"STEP-015","status":"BLOCKED","notes":"Cannot access files"}\nMore output'

        with patch("tools.orchestrator.copilot_cli_adapter.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=["copilot"], returncode=0, stdout=stdout, stderr=""
            )
            result = adapter.invoke(request)

        assert result.status == "BLOCKED"
        assert result.notes == "Cannot access files"

    def test_agent_done_json_with_exit_code_zero_returns_done(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        adapter = CopilotCliAdapter(make_default_config(), tmp_path / ".automation")
        stdout = '{"schema_version":1,"step_id":"STEP-015","status":"DONE","notes":"All good"}'

        with patch("tools.orchestrator.copilot_cli_adapter.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=["copilot"], returncode=0, stdout=stdout, stderr=""
            )
            result = adapter.invoke(request)

        assert result.status == "DONE"
        assert result.notes == "All good"

    def test_exit_code_zero_without_agent_json_returns_failed_result(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        adapter = CopilotCliAdapter(make_default_config(), tmp_path / ".automation")

        with patch("tools.orchestrator.copilot_cli_adapter.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=["copilot"], returncode=0, stdout="plain text output only", stderr=""
            )
            result = adapter.invoke(request)

        assert result.status == "FAILED"
        assert result.stop_condition_hit is None
        assert result.notes is not None
        assert "agent-result JSON" in result.notes

    def test_agent_json_stop_condition_forwarded(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        adapter = CopilotCliAdapter(make_default_config(), tmp_path / ".automation")
        stdout = '{"schema_version":1,"step_id":"STEP-015","status":"BLOCKED","stop_condition_hit":"max_retries"}'

        with patch("tools.orchestrator.copilot_cli_adapter.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=["copilot"], returncode=0, stdout=stdout, stderr=""
            )
            result = adapter.invoke(request)

        assert result.status == "BLOCKED"
        assert result.stop_condition_hit == "max_retries"

    def test_failed_invocation_returns_blocked_result(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        adapter = CopilotCliAdapter(make_default_config(), tmp_path / ".automation")

        with patch("tools.orchestrator.copilot_cli_adapter.subprocess.run") as run_mock:
            run_mock.return_value = _completed_process(returncode=17)

            result = adapter.invoke(request)

        assert result.schema_version == 1
        assert result.step_id == "STEP-015"
        assert result.status == "BLOCKED"
        assert result.stop_condition_hit == "copilot_exit_code_17"

    def test_timeout_returns_blocked_result(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        config = make_default_config(copilot_cli=CopilotCliConfig(timeout_seconds=12, allow_tools=BUILTIN_ALLOW_TOOLS, deny_tools=BUILTIN_DENY_TOOLS))
        adapter = CopilotCliAdapter(config, tmp_path / ".automation")

        with patch("tools.orchestrator.copilot_cli_adapter.subprocess.run") as run_mock:
            run_mock.side_effect = subprocess.TimeoutExpired(
                cmd=["copilot"],
                timeout=12,
            )

            result = adapter.invoke(request)

        assert result.schema_version == 1
        assert result.step_id == "STEP-015"
        assert result.status == "BLOCKED"
        assert result.stop_condition_hit == "timeout"

    def test_missing_system_prompt_returns_blocked_without_invoking_copilot(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        request.system_prompt_path = str(tmp_path / "missing-system-prompt.md")
        adapter = CopilotCliAdapter(make_default_config(), tmp_path / ".automation")

        with patch("tools.orchestrator.copilot_cli_adapter.subprocess.run") as run_mock:
            result = adapter.invoke(request)

        run_mock.assert_not_called()
        assert result.schema_version == 1
        assert result.step_id == "STEP-015"
        assert result.status == "BLOCKED"
        assert result.stop_condition_hit is not None
        assert "system_prompt" in result.stop_condition_hit


class TestCopilotCliAdapterConfigToolPermissions:
    """Verify the adapter reads tool permissions and timeout from config."""

    def test_custom_allow_tools_from_config(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        config = make_default_config(
            copilot_cli=CopilotCliConfig(timeout_seconds=600, allow_tools=("write", "shell(node)"), deny_tools=BUILTIN_DENY_TOOLS)
        )
        adapter = CopilotCliAdapter(config, tmp_path / ".automation")

        command = _invoke_and_get_command(adapter, request)
        allow_flags = [a for a in command if a.startswith("--allow-tool=")]

        assert allow_flags == ["--allow-tool=write", "--allow-tool=shell(node)"]

    def test_custom_deny_tools_from_config(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        config = make_default_config(
            copilot_cli=CopilotCliConfig(timeout_seconds=600, allow_tools=BUILTIN_ALLOW_TOOLS, deny_tools=("shell(rm)", "shell(docker)"))
        )
        adapter = CopilotCliAdapter(config, tmp_path / ".automation")

        command = _invoke_and_get_command(adapter, request)
        deny_flags = [a for a in command if a.startswith("--deny-tool=")]

        assert deny_flags == ["--deny-tool=shell(rm)", "--deny-tool=shell(docker)"]

    def test_empty_allow_tools_produces_no_allow_flags(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        config = make_default_config(copilot_cli=CopilotCliConfig(timeout_seconds=600, allow_tools=(), deny_tools=BUILTIN_DENY_TOOLS))
        adapter = CopilotCliAdapter(config, tmp_path / ".automation")

        command = _invoke_and_get_command(adapter, request)
        allow_flags = [a for a in command if a.startswith("--allow-tool=")]

        assert allow_flags == []

    def test_empty_deny_tools_produces_no_deny_flags(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        config = make_default_config(copilot_cli=CopilotCliConfig(timeout_seconds=600, allow_tools=BUILTIN_ALLOW_TOOLS, deny_tools=()))
        adapter = CopilotCliAdapter(config, tmp_path / ".automation")

        command = _invoke_and_get_command(adapter, request)
        deny_flags = [a for a in command if a.startswith("--deny-tool=")]

        assert deny_flags == []

    def test_timeout_from_config(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        config = make_default_config(copilot_cli=CopilotCliConfig(timeout_seconds=120, allow_tools=BUILTIN_ALLOW_TOOLS, deny_tools=BUILTIN_DENY_TOOLS))
        adapter = CopilotCliAdapter(config, tmp_path / ".automation")

        with patch("tools.orchestrator.copilot_cli_adapter.subprocess.run") as run_mock:
            run_mock.return_value = _completed_process()
            adapter.invoke(request)

        assert run_mock.call_args.kwargs["timeout"] == 120


# ---------------------------------------------------------------------------
# Phase 9b — worker message assembled in code from structured context
# ---------------------------------------------------------------------------


def _make_phase9b_request(tmp_path: Path) -> AgentInvocationRequest:
    system_prompt = tmp_path / "prompts" / "system_prompt.implementation.md"
    system_prompt.parent.mkdir(parents=True, exist_ok=True)
    system_prompt.write_text(
        "You execute exactly one bounded step and modify only allowed files.\n",
        encoding="utf-8",
    )
    request = AgentInvocationRequest(
        step_id="STEP-042",
        agent_name="default.wfrunner",
        model="default",
        system_prompt_path=str(system_prompt),
        step_prompt="Implement the parser and keep it importable.",
        plan_context="This project orchestrates AI-assisted implementation.",
        allowed_files=["tools/parser.py"],
        verification_commands=["python -m pytest tests/test_parser.py -q"],
    )
    request.title = "Implement the parser"
    return request


class TestCopilotCliAdapterMessageAssembly:
    """Phase 9b: the worker message is assembled from system prompt, plan context, step prompt, and metadata."""

    def test_assembled_message_contains_all_layers(self, tmp_path: Path) -> None:
        request = _make_phase9b_request(tmp_path)
        adapter = CopilotCliAdapter(make_default_config(), tmp_path / ".automation")

        command = _invoke_and_get_command(adapter, request)
        message = _option_value(command, "-p")

        assert "You execute exactly one bounded step" in message
        assert "This project orchestrates AI-assisted implementation." in message
        assert "Implement the parser and keep it importable." in message
        assert "STEP-042" in message
        assert "tools/parser.py" in message
        assert "python -m pytest tests/test_parser.py -q" in message

    def test_assembled_message_does_not_point_to_source_plan(self, tmp_path: Path) -> None:
        request = _make_phase9b_request(tmp_path)
        adapter = CopilotCliAdapter(make_default_config(), tmp_path / ".automation")

        command = _invoke_and_get_command(adapter, request)
        message = _option_value(command, "-p")

        assert "implementation plan at" not in message.lower()
        assert "locate step" not in message.lower()

    def test_agent_name_passed_through(self, tmp_path: Path) -> None:
        request = _make_phase9b_request(tmp_path)
        request.agent_name = "cppagent"
        adapter = CopilotCliAdapter(make_default_config(), tmp_path / ".automation")

        command = _invoke_and_get_command(adapter, request)

        assert _option_value(command, "--agent") == "cppagent"

    def test_failure_context_appended(self, tmp_path: Path) -> None:
        request = _make_phase9b_request(tmp_path)
        request.failure_context = {"exit_code": 1, "stderr_tail": "boom"}
        adapter = CopilotCliAdapter(make_default_config(), tmp_path / ".automation")

        command = _invoke_and_get_command(adapter, request)
        message = _option_value(command, "-p")

        assert "boom" in message


class TestCopilotCliAdapterEncoding:
    """Regression: subprocess.run must use explicit tolerant UTF-8 decoding on Windows."""

    def test_subprocess_run_uses_explicit_utf8_encoding(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        adapter = CopilotCliAdapter(make_default_config(), tmp_path / ".automation")

        with patch("tools.orchestrator.copilot_cli_adapter.subprocess.run") as run_mock:
            run_mock.return_value = _completed_process()

            adapter.invoke(request)

        kwargs = run_mock.call_args.kwargs
        assert kwargs.get("encoding") == "utf-8", (
            "subprocess.run must pass encoding='utf-8' to avoid UnicodeDecodeError on Windows"
        )
        assert kwargs.get("errors") == "replace", (
            "subprocess.run must pass errors='replace' to tolerate non-UTF-8 Copilot CLI output"
        )

    def test_subprocess_runs_without_explicit_cwd(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        adapter = CopilotCliAdapter(make_default_config(), tmp_path / ".automation")

        with patch("tools.orchestrator.copilot_cli_adapter.subprocess.run") as run_mock:
            run_mock.return_value = _completed_process()

            adapter.invoke(request)

        assert "cwd" not in run_mock.call_args.kwargs, (
            "subprocess.run must not set cwd so the agent inherits the project root"
        )


class TestCopilotCliAdapterLogging:
    """Verify agent invocation output is written to the automation log."""

    def test_logs_invocation_to_step_log(self, tmp_path: Path) -> None:
        request = _make_request(tmp_path)
        automation_dir = tmp_path / ".automation"
        adapter = CopilotCliAdapter(make_default_config(), automation_dir)

        with patch("tools.orchestrator.copilot_cli_adapter.subprocess.run") as run_mock:
            run_mock.return_value = _completed_process(returncode=0)

            adapter.invoke(request)

        log_path = automation_dir / "agent-logs" / "STEP-015.log"
        assert log_path.exists()
        log_text = log_path.read_text(encoding="utf-8")
        assert "agent output" in log_text
        assert "agent error" in log_text
