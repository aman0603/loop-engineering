from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from core.artifacts import Artifact
from core.execution import ExecutionContext
from core.planning import ExecutionStep


@dataclass(frozen=True, slots=True)
class AgentCapability:
    name: str
    tools: list[str] = field(default_factory=list)
    cost_weight: float = 1
    latency_weight: float = 1


@dataclass(frozen=True, slots=True)
class AgentHealth:
    available: bool
    provider: str
    model: str
    details: dict[str, Any] = field(default_factory=dict)


class AgentResponseStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class AgentOutputChunk:
    session_id: str
    content: str
    index: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentResponse:
    status: AgentResponseStatus
    reasoning_summary: str
    artifacts: list[Artifact] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    execution_metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    session_id: str | None = None

    @property
    def success(self) -> bool:
        return self.status == AgentResponseStatus.SUCCEEDED


class AgentAdapter(ABC):
    name: str
    provider: str
    model: str

    def initialize(self, context: ExecutionContext) -> None:
        return None

    @abstractmethod
    def capabilities(self) -> list[AgentCapability]:
        raise NotImplementedError

    @abstractmethod
    def execute(self, step: ExecutionStep, context: ExecutionContext) -> AgentResponse:
        raise NotImplementedError

    def stream(self, step: ExecutionStep, context: ExecutionContext) -> Iterable[AgentOutputChunk]:
        response = self.execute(step, context)
        if response.reasoning_summary:
            yield AgentOutputChunk(response.session_id or "", response.reasoning_summary, 0)

    def cancel(self, session_id: str) -> bool:
        return False

    def health(self) -> AgentHealth:
        return AgentHealth(available=True, provider=self.provider, model=self.model)

    def estimate_cost(self, step: ExecutionStep, context: ExecutionContext) -> float:
        return 0

    def estimate_latency(self, step: ExecutionStep, context: ExecutionContext) -> float:
        return 0

