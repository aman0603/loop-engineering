from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.events import Event, EventType
from core.execution import ExecutionContext
from core.task_manager.models import Task
from skills.base import Skill, SkillContext


@dataclass(slots=True)
class AgentMessage:
    sender: str
    kind: str
    content: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentResult:
    success: bool
    outputs: dict[str, Any] = field(default_factory=dict)
    messages: list[AgentMessage] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class Agent(ABC):
    name: str

    @abstractmethod
    def handle(self, context: ExecutionContext) -> AgentResult:
        raise NotImplementedError


class SkillAgent(Agent):
    def __init__(self, name: str, skill: Skill) -> None:
        self.name = name
        self.skill = skill

    def handle(
        self,
        context_or_task: ExecutionContext | Task,
        maybe_context: SkillContext | ExecutionContext | None = None,
    ) -> AgentResult:
        if isinstance(context_or_task, ExecutionContext):
            context = context_or_task
        elif isinstance(maybe_context, ExecutionContext):
            context = maybe_context
            context.task = context_or_task
        else:
            context = ExecutionContext(task=context_or_task)
            if isinstance(maybe_context, SkillContext):
                context.merge_artifacts(maybe_context.artifacts)
                context.feedback = maybe_context.feedback
                context.execution_metadata.update(maybe_context.metadata)

        context.current_agent = self.name
        context.current_skill = self.skill.name
        context.emit(Event(EventType.SKILL_STARTED, context.task.id, {"agent": self.name, "skill": self.skill.name}))
        result = self.skill.execute(context)
        context.emit(
            Event(
                EventType.SKILL_FINISHED,
                context.task.id,
                {"agent": self.name, "skill": self.skill.name, "success": result.success},
            )
        )

        for artifact in result.artifacts:
            context.add_artifact(artifact)
        if result.output:
            artifact_types = {
                artifact.type.value if hasattr(artifact.type, "value") else str(artifact.type)
                for artifact in result.artifacts
            }
            legacy_outputs = {
                name: value
                for name, value in result.output.items()
                if name not in artifact_types
            }
            context.merge_artifacts(legacy_outputs, producer=self.skill.name)
        for name, value in result.metrics.items():
            context.metrics.set(name, value)
            context.task.metrics[name] = value
        for message in result.logs:
            context.log(self.name, message, kind="log")

        messages = [
            AgentMessage(sender=self.name, kind="log", content=message)
            for message in result.logs
        ]
        return AgentResult(
            success=result.success,
            outputs=result.output,
            messages=messages,
            errors=result.errors,
            metrics=result.metrics,
        )
