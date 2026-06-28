from __future__ import annotations

import time
from typing import Iterable

from agents.adapters.base import (
    AgentAdapter,
    AgentCapability,
    AgentHealth,
    AgentOutputChunk,
    AgentResponse,
    AgentResponseStatus,
)
from core.events import Event, EventType
from core.artifacts import Artifact
from core.execution import ExecutionContext
from core.planning import ExecutionStep


class MockAgentAdapter(AgentAdapter):
    name = "mock.agent"
    provider = "mock"
    model = "mock-model"

    def __init__(
        self,
        name: str | None = None,
        capabilities: list[str] | None = None,
        fail_for_steps: set[str] | None = None,
        unavailable: bool = False,
    ) -> None:
        if name is not None:
            self.name = name
        self._capabilities = capabilities or [
            "planning",
            "coding",
            "review",
            "debugging",
            "documentation",
            "testing",
            "refactoring",
            "architecture",
            "research",
        ]
        self.fail_for_steps = fail_for_steps or set()
        self.unavailable = unavailable
        self.cancelled_sessions: set[str] = set()

    def capabilities(self) -> list[AgentCapability]:
        return [AgentCapability(name=item) for item in self._capabilities]

    def execute(self, step: ExecutionStep, context: ExecutionContext) -> AgentResponse:
        started = time.monotonic()
        session = context.start_agent_session(
            provider=self.provider,
            model=self.model,
            active_step=step.id,
            workflow_id=context.current_workflow,
        )
        if step.id in self.fail_for_steps or not self.health().available:
            context.finish_agent_session(session.id, failed=True)
            return AgentResponse(
                status=AgentResponseStatus.FAILED,
                reasoning_summary=f"mock adapter failed {step.id}",
                errors=[f"mock failure for {step.id}"],
                execution_metrics={"latency_ms": (time.monotonic() - started) * 1000},
                session_id=session.id,
            )

        artifacts = [
            Artifact(
                artifact_type,
                self.name,
                {"step_id": step.id, "capability": step.required_capability, "provider": self.provider},
            )
            for artifact_type in (step.expected_artifacts or ["log"])
        ]
        for artifact in artifacts:
            context.add_artifact(artifact)
        context.finish_agent_session(session.id, artifacts=artifacts)
        return AgentResponse(
            status=AgentResponseStatus.SUCCEEDED,
            reasoning_summary=f"mock completed {step.description}",
            artifacts=artifacts,
            tool_calls=[],
            execution_metrics={"latency_ms": (time.monotonic() - started) * 1000, "cost": 0},
            session_id=session.id,
        )

    def stream(self, step: ExecutionStep, context: ExecutionContext) -> Iterable[AgentOutputChunk]:
        session = context.start_agent_session(
            provider=self.provider,
            model=self.model,
            active_step=step.id,
            workflow_id=context.current_workflow,
        )
        context.emit(Event(EventType.AGENT_STARTED, context.task.id, {"adapter": self.name, "step_id": step.id, "session_id": session.id}))
        for index, chunk in enumerate(["mock ", "adapter ", "output"]):
            output = AgentOutputChunk(session.id, chunk, index, {"step_id": step.id})
            context.emit(Event(EventType.AGENT_OUTPUT_CHUNK, context.task.id, {"session_id": session.id, "content": chunk, "index": index}))
            yield output
        context.finish_agent_session(session.id)
        context.emit(Event(EventType.AGENT_FINISHED, context.task.id, {"adapter": self.name, "step_id": step.id, "session_id": session.id}))

    def cancel(self, session_id: str) -> bool:
        self.cancelled_sessions.add(session_id)
        return True

    def health(self) -> AgentHealth:
        return AgentHealth(available=not self.unavailable, provider=self.provider, model=self.model)

    def estimate_cost(self, step: ExecutionStep, context: ExecutionContext) -> float:
        return 0

    def estimate_latency(self, step: ExecutionStep, context: ExecutionContext) -> float:
        return 1
