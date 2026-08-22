"""Agent invocation — orchestrator-side logic for invoking and validating agent results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

from tools.constants import AGENT_STATUS_BLOCKED, AGENT_STATUS_FAILED
from tools.data_path import require_runtime_resource
from tools.orchestrator.agent_adapter import AgentAdapter, AgentInvocationRequest, AgentResult


def _load_agent_result_schema() -> dict[str, Any]:
    """Load the agent-result JSON schema."""
    schema_path = require_runtime_resource(
        Path("schemas") / "agent-result.schema.json",
        description="agent result schema",
    )
    return json.loads(schema_path.read_text(encoding="utf-8"))


@dataclass
class AgentInvocationResult:
    """Result of agent invocation including validation."""

    agent_result: AgentResult | None = None
    ok: bool = True
    blocked: bool = False
    failed: bool = False
    invalid_result: bool = False
    failure_reason: str | None = None


def invoke_agent(
    adapter: AgentAdapter,
    request: AgentInvocationRequest,
) -> AgentInvocationResult:
    """Invoke the agent and validate its result.

    Args:
        adapter: The agent adapter to use.
        request: The invocation request.

    Returns:
        An AgentInvocationResult with validation outcome.
    """
    agent_result = adapter.invoke(request)

    # Validate the result against the agent-result schema.
    result_dict = agent_result.to_dict()

    # If the agent provided raw_json, validate that instead — it may
    # contain extra or missing fields the to_dict() would hide.
    validation_target = agent_result.raw_json if agent_result.raw_json is not None else result_dict

    try:
        schema = _load_agent_result_schema()
        jsonschema.validate(instance=validation_target, schema=schema)
    except jsonschema.ValidationError as exc:
        return AgentInvocationResult(
            agent_result=agent_result,
            ok=False,
            invalid_result=True,
            failure_reason=f"Agent result schema validation failed: {exc.message}",
        )

    # Check step_id match.
    if agent_result.step_id != request.step_id:
        return AgentInvocationResult(
            agent_result=agent_result,
            ok=False,
            invalid_result=True,
            failure_reason=(
                f"Agent returned step_id '{agent_result.step_id}' "
                f"but expected '{request.step_id}' (mismatch)."
            ),
        )

    # Handle BLOCKED status.
    if agent_result.status == AGENT_STATUS_BLOCKED:
        return AgentInvocationResult(
            agent_result=agent_result,
            ok=False,
            blocked=True,
        )

    if agent_result.status == AGENT_STATUS_FAILED:
        notes = f": {agent_result.notes}" if agent_result.notes else "."
        return AgentInvocationResult(
            agent_result=agent_result,
            ok=False,
            failed=True,
            failure_reason=f"Agent returned status FAILED{notes}",
        )

    return AgentInvocationResult(
        agent_result=agent_result,
        ok=True,
        blocked=False,
    )
