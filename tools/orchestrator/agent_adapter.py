"""Agent adapter — abstract interface for worker agent invocation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class AgentInvocationRequest:
    """Request payload for invoking a worker agent.

    The worker message is assembled in code from the per-type system prompt,
    the shared plan context, the compiled step prompt, and structured metadata.
    """

    step_id: str
    agent_name: str
    model: str
    system_prompt_path: str
    step_prompt: str
    plan_context: str
    allowed_files: list[str]
    verification_commands: list[str]
    failure_context: dict[str, Any] | None = None
    title: str = ""


@dataclass
class AgentResult:
    """Result returned by a worker agent."""

    schema_version: int
    step_id: str
    status: str  # "DONE", "FAILED", or "BLOCKED"
    notes: str | None = None
    stop_condition_hit: str | None = None
    raw_json: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict matching the agent-result schema."""
        d: dict[str, Any] = {
            "schema_version": self.schema_version,
            "step_id": self.step_id,
            "status": self.status,
        }
        if self.notes is not None:
            d["notes"] = self.notes
        if self.stop_condition_hit is not None:
            d["stop_condition_hit"] = self.stop_condition_hit
        return d


class AgentAdapter(ABC):
    """Abstract base class for agent adapters.

    The orchestrator depends only on this interface.  Concrete
    implementations include the real Copilot CLI adapter (production)
    and the FakeAgentAdapter (tests).
    """

    @abstractmethod
    def invoke(self, request: AgentInvocationRequest) -> AgentResult:
        """Invoke the agent for a single step and return its result.

        Implementations must:
        - Execute or simulate agent work for the requested step.
        - Return exactly one AgentResult.
        - Not modify files outside the request's allowed_files
          (enforcement is orchestrator-owned, but adapters should
          cooperate).

        Args:
            request: The invocation request describing the step.

        Returns:
            An AgentResult with the agent's outcome.
        """
