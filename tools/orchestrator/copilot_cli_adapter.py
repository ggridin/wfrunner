"""Copilot CLI adapter for invoking worker agents."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tools.config import WaterfallRunnerConfig
from tools.constants import (
    AGENT_STATUS_BLOCKED,
    AGENT_STATUS_DONE,
    AGENT_STATUS_FAILED,
    MODEL_DEFAULT,
)
from tools.orchestrator.agent_adapter import AgentAdapter, AgentInvocationRequest, AgentResult


class CopilotCliAdapter(AgentAdapter):
    """Agent adapter backed by the Copilot CLI programmatic interface."""

    def __init__(
        self,
        config: WaterfallRunnerConfig,
        automation_dir: Path,
    ) -> None:
        self.config = config
        self.automation_dir = Path(automation_dir)

    def invoke(self, request: AgentInvocationRequest) -> AgentResult:
        """Invoke Copilot for a single implementation step."""
        try:
            message = self._assemble_message(request)
        except OSError as exc:
            return AgentResult(
                schema_version=1,
                step_id=request.step_id,
                status=AGENT_STATUS_BLOCKED,
                notes=f"Could not read system prompt: {exc}",
                stop_condition_hit=f"system_prompt_unavailable:{request.system_prompt_path}",
            )
        agent_name = self.config.resolve_agent(request.agent_name)
        model = self.config.resolve_model(request.model)
        command = [
            self.config.copilot_command,
            "--agent",
            agent_name,
            "-p",
            message,
        ]
        # Omit --model when it stays the sentinel so the value "default" is
        # never sent to the CLI as a literal model name; let the CLI choose.
        if model != MODEL_DEFAULT:
            command.extend(["--model", model])
        for tool in self.config.copilot_cli.allow_tools:
            command.append(f"--allow-tool={tool}")
        for tool in self.config.copilot_cli.deny_tools:
            command.append(f"--deny-tool={tool}")

        timeout = self.config.copilot_cli.timeout_seconds

        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            self._write_log(request.step_id, command, timeout=exc)
            return AgentResult(
                schema_version=1,
                step_id=request.step_id,
                status=AGENT_STATUS_BLOCKED,
                stop_condition_hit="timeout",
            )

        self._write_log(request.step_id, command, completed=completed)

        if completed.returncode == 0:
            extracted = self._extract_agent_result(completed.stdout, request.step_id)
            if extracted is not None:
                return extracted
            return AgentResult(
                schema_version=1,
                step_id=request.step_id,
                status=AGENT_STATUS_FAILED,
                notes="Copilot CLI exited 0 without returning required agent-result JSON.",
                raw_json={
                    "schema_version": 1,
                    "step_id": request.step_id,
                    "notes": "Copilot CLI exited 0 without returning required agent-result JSON.",
                },
            )

        return AgentResult(
            schema_version=1,
            step_id=request.step_id,
            status=AGENT_STATUS_BLOCKED,
            stop_condition_hit=f"copilot_exit_code_{completed.returncode}",
        )

    def _extract_agent_result(self, stdout: str, step_id: str) -> AgentResult | None:
        """Scan stdout for a JSON agent-result object, searching from the end."""
        if not stdout:
            return None

        # Search backward through lines for JSON objects
        lines = stdout.splitlines()
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i].strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            if (
                isinstance(obj, dict)
                and obj.get("schema_version") == 1
                and "step_id" in obj
                and "status" in obj
            ):
                return AgentResult(
                    schema_version=1,
                    step_id=obj.get("step_id", step_id),
                    status=obj["status"],
                    notes=obj.get("notes"),
                    stop_condition_hit=obj.get("stop_condition_hit"),
                    raw_json=obj,
                )

        return None

    def _assemble_message(self, request: AgentInvocationRequest) -> str:
        """Assemble the worker message from structured context.

        The message layers the per-type system prompt, the shared plan context,
        the compiled step prompt, and structured metadata. It never instructs
        the worker to locate its step in the source plan.
        """
        system_prompt = Path(request.system_prompt_path).read_text(encoding="utf-8").rstrip()
        allowed_files = "\n".join(f"- {path}" for path in request.allowed_files)
        verification_commands = "\n".join(f"- {command}" for command in request.verification_commands)

        sections = [
            system_prompt,
            "## Plan context\n\n" + request.plan_context.strip(),
            "## Task\n\n" + request.step_prompt.strip(),
            (
                "## Step metadata\n\n"
                f"- Step ID: {request.step_id}\n"
                f"- Title: {request.title}\n"
                "- Allowed files:\n"
                f"{allowed_files}\n"
                "- Verification commands:\n"
                f"{verification_commands}"
            ),
        ]
        message = "\n\n".join(sections)

        if request.failure_context is not None:
            message += "\n\n## Verification Failure Context\n\n"
            message += "\n".join(
                f"- {key}: {value}" for key, value in request.failure_context.items()
            )

        return message

    def _write_log(
        self,
        step_id: str,
        command: list[str],
        completed: subprocess.CompletedProcess[str] | None = None,
        timeout: subprocess.TimeoutExpired | None = None,
    ) -> None:
        """Write a per-step Copilot invocation log."""
        log_dir = self.automation_dir / "agent-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{step_id}.log"

        lines = [
            "Command:",
            " ".join(command),
            "",
        ]
        if completed is not None:
            lines.extend(
                [
                    f"Exit code: {completed.returncode}",
                    "",
                    "STDOUT:",
                    completed.stdout or "",
                    "",
                    "STDERR:",
                    completed.stderr or "",
                ]
            )
        elif timeout is not None:
            lines.extend(
                [
                    f"Timed out after {timeout.timeout} seconds.",
                    "",
                    "STDOUT:",
                    _coerce_output(timeout.output),
                    "",
                    "STDERR:",
                    _coerce_output(timeout.stderr),
                ]
            )

        log_path.write_text("\n".join(lines), encoding="utf-8")


def _coerce_output(output: str | bytes | None) -> str:
    """Convert subprocess timeout output to text for logs."""
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode(errors="replace")
    return output
