from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.artifacts import Artifact
from core.execution import ExecutionContext


@dataclass(slots=True)
class ToolContext:
    execution: ExecutionContext
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    artifacts: list[Artifact] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class Tool(ABC):
    name: str

    def initialize(self, context: ExecutionContext) -> None:
        return None

    @abstractmethod
    def execute(self, context: ExecutionContext, request: Any = None) -> ToolResult:
        raise NotImplementedError

    def validate(self, context: ExecutionContext, result: ToolResult) -> ToolResult:
        return result

    def cleanup(self, context: ExecutionContext) -> None:
        return None

    def run(self, context: ExecutionContext, request: Any = None) -> ToolResult:
        self.initialize(context)
        try:
            result = self.execute(context, request)
            result = self.validate(context, result)
        finally:
            self.cleanup(context)
        for artifact in result.artifacts:
            context.add_artifact(artifact)
        for name, value in result.metrics.items():
            context.metrics.set(name, value)
        return result

