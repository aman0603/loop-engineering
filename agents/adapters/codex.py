from __future__ import annotations

import json
import time
from typing import Iterable

from agents.adapters.base import AgentAdapter, AgentCapability, AgentOutputChunk, AgentResponse, AgentResponseStatus
from core.events import Event, EventType
from core.artifacts import Artifact, RuntimeLogArtifact
from core.execution import ExecutionContext
from core.planning import ExecutionStep
from runtime import CommandSpec, LocalRuntime, Runtime


class CodexCLIAdapter(AgentAdapter):
    name = "codex.cli"
    provider = "codex"

    def __init__(
        self,
        model: str = "codex-default",
        runtime: Runtime | None = None,
        executable: str = "codex",
        capabilities: list[str] | None = None,
    ) -> None:
        self.model = model
        self.runtime = runtime or LocalRuntime()
        self.executable = executable
        self._capabilities = capabilities or [
            "planning",
            "coding",
            "review",
            "debugging",
            "documentation",
            "testing",
            "refactoring",
            "architecture",
        ]

    def capabilities(self) -> list[AgentCapability]:
        return [AgentCapability(name=item, tools=["shell", "filesystem"]) for item in self._capabilities]

    def execute(self, step: ExecutionStep, context: ExecutionContext) -> AgentResponse:
        started = time.monotonic()
        session = context.start_agent_session(
            provider=self.provider,
            model=self.model,
            active_step=step.id,
            workflow_id=context.current_workflow,
        )
        prompt = self.build_prompt(step, context)
        result = self.runtime.execute(
            CommandSpec(
                args=[self.executable, "exec", prompt],
                cwd=context.working_directory,
                timeout_seconds=step.timeout or context.configuration.command_timeout_seconds,
                name="codex.cli",
            ),
            context,
        ).result
        artifact = RuntimeLogArtifact(
            self.name,
            {"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.exit_code, "step_id": step.id},
            session_id=session.id,
        )
        context.add_artifact(artifact)
        status = AgentResponseStatus.SUCCEEDED if result.success else AgentResponseStatus.FAILED
        context.finish_agent_session(session.id, failed=not result.success, artifacts=[artifact])
        return AgentResponse(
            status=status,
            reasoning_summary=result.stdout.strip()[:500],
            artifacts=[artifact],
            tool_calls=[{"tool": "codex_cli", "args": ["exec"]}],
            execution_metrics={"latency_ms": (time.monotonic() - started) * 1000, "exit_code": result.exit_code},
            warnings=[],
            errors=[] if result.success else [result.stderr or result.stdout],
            session_id=session.id,
        )

    def stream(self, step: ExecutionStep, context: ExecutionContext) -> Iterable[AgentOutputChunk]:
        context.emit(Event(EventType.AGENT_STARTED, context.task.id, {"adapter": self.name, "step_id": step.id}))
        response = self.execute(step, context)
        output = response.reasoning_summary or "\n".join(response.errors)
        for index, line in enumerate(output.splitlines() or [output]):
            chunk = AgentOutputChunk(response.session_id or "", line, index, {"adapter": self.name})
            context.emit(Event(EventType.AGENT_OUTPUT_CHUNK, context.task.id, {"session_id": chunk.session_id, "content": line, "index": index}))
            yield chunk
        context.emit(
            Event(
                EventType.AGENT_FINISHED if response.success else EventType.AGENT_FAILED,
                context.task.id,
                {"adapter": self.name, "step_id": step.id, "session_id": response.session_id},
            )
        )

    def cancel(self, session_id: str) -> bool:
        return True

    def estimate_cost(self, step: ExecutionStep, context: ExecutionContext) -> float:
        return float(step.metadata.get("estimated_tokens", 1000)) / 100000

    def estimate_latency(self, step: ExecutionStep, context: ExecutionContext) -> float:
        return float(step.metadata.get("estimated_latency_ms", 5000))

    def build_prompt(self, step: ExecutionStep, context: ExecutionContext) -> str:
        payload = {
            "task": {
                "id": context.task.id,
                "title": context.task.title,
                "description": context.task.description,
                "goal": context.task.goal,
                "acceptance_criteria": context.task.acceptance_criteria,
            },
            "step": step.to_dict(),
            "runtime": {
                "workflow": context.current_workflow,
                "working_directory": str(context.working_directory) if context.working_directory else None,
                "available_artifacts": [artifact.to_dict() for artifact in context.artifact_store.list()],
            },
        }
        return json.dumps(payload, sort_keys=True)
