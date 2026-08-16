"""Fake agent adapter — deterministic agent for orchestrator TDD."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from tools.orchestrator.agent_adapter import AgentAdapter, AgentInvocationRequest, AgentResult
from tools.constants import AGENT_STATUS_BLOCKED, AGENT_STATUS_DONE, AGENT_STATUS_FAILED


@dataclass
class FileAction:
    """Describes a file-system action the fake agent should perform."""

    path: str
    content: str
    action: str = "write"  # "write" (create or overwrite), "modify", "delete"


@dataclass
class FakeAgentBehavior:
    """Configurable deterministic behavior for one invocation.

    Attributes:
        result: The AgentResult to return.
        file_actions: File-system side effects to simulate.
        raw_json_override: If set, the adapter returns this raw JSON string
            instead of a well-formed AgentResult.  Useful for testing
            malformed-result handling.
    """

    result: AgentResult
    file_actions: list[FileAction] = field(default_factory=list)
    raw_json_override: str | None = None


class FakeAgentAdapter(AgentAdapter):
    """A deterministic agent adapter for testing.

    Behaviors are enqueued and consumed in FIFO order.  If no behaviors
    remain, the adapter raises RuntimeError so tests fail loudly.

    The adapter records every invocation request for later assertions.
    """

    def __init__(self) -> None:
        self._behaviors: list[FakeAgentBehavior] = []
        self.invocations: list[AgentInvocationRequest] = []

    # ── Configuration helpers ────────────────────────────────────────

    def enqueue(self, behavior: FakeAgentBehavior) -> None:
        """Add a behavior to the FIFO queue."""
        self._behaviors.append(behavior)

    def enqueue_done(
        self,
        step_id: str,
        file_actions: list[FileAction] | None = None,
        notes: str | None = None,
    ) -> None:
        """Shortcut: enqueue a DONE result with optional file actions."""
        self.enqueue(
            FakeAgentBehavior(
                result=AgentResult(
                    schema_version=1,
                    step_id=step_id,
                    status=AGENT_STATUS_DONE,
                    notes=notes,
                ),
                file_actions=file_actions or [],
            )
        )

    def enqueue_failed(self, step_id: str, notes: str | None = None) -> None:
        """Shortcut: enqueue a FAILED result."""
        self.enqueue(
            FakeAgentBehavior(
                result=AgentResult(
                    schema_version=1,
                    step_id=step_id,
                    status=AGENT_STATUS_FAILED,
                    notes=notes,
                ),
            )
        )

    def enqueue_blocked(
        self,
        step_id: str,
        stop_condition: str,
        notes: str | None = None,
    ) -> None:
        """Shortcut: enqueue a BLOCKED result with stop_condition_hit."""
        self.enqueue(
            FakeAgentBehavior(
                result=AgentResult(
                    schema_version=1,
                    step_id=step_id,
                    status=AGENT_STATUS_BLOCKED,
                    stop_condition_hit=stop_condition,
                    notes=notes,
                ),
            )
        )

    def enqueue_malformed_json(self, raw_json: str) -> None:
        """Shortcut: enqueue a raw JSON string that may be malformed."""
        self.enqueue(
            FakeAgentBehavior(
                result=AgentResult(schema_version=1, step_id="", status=AGENT_STATUS_DONE),
                raw_json_override=raw_json,
            )
        )

    def enqueue_mismatched_step(
        self,
        _expected_step_id: str,
        returned_step_id: str,
    ) -> None:
        """Shortcut: enqueue a result whose step_id doesn't match the request."""
        self.enqueue(
            FakeAgentBehavior(
                result=AgentResult(
                    schema_version=1,
                    step_id=returned_step_id,
                    status=AGENT_STATUS_DONE,
                ),
            )
        )

    @property
    def remaining_behaviors(self) -> int:
        """Number of unconsumed behaviors."""
        return len(self._behaviors)

    # ── AgentAdapter implementation ──────────────────────────────────

    def invoke(self, request: AgentInvocationRequest) -> AgentResult:
        """Consume the next enqueued behavior, apply file actions, return result."""
        self.invocations.append(request)

        if not self._behaviors:
            raise RuntimeError(
                f"FakeAgentAdapter: no behaviors enqueued for step {request.step_id}"
            )

        behavior = self._behaviors.pop(0)

        # Apply file-system side effects relative to the working directory.
        for action in behavior.file_actions:
            path = Path(action.path)
            if action.action in ("write", "modify"):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(action.content, encoding="utf-8")
            elif action.action == "delete":
                if path.exists():
                    path.unlink()

        # If a raw JSON override is set, attach it so the orchestrator
        # can detect malformed results during schema validation.
        result = behavior.result
        if behavior.raw_json_override is not None:
            try:
                result.raw_json = json.loads(behavior.raw_json_override)
            except json.JSONDecodeError:
                result.raw_json = None  # truly malformed
            # Still return the result — the orchestrator validates it.

        return result
