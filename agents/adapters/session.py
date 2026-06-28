from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from core.artifacts import Artifact


class AgentSessionStatus(str, Enum):
    INITIALIZED = "INITIALIZED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(slots=True)
class AgentSession:
    task_id: str
    workflow_id: str | None
    active_step: str
    provider: str
    model: str
    id: str = field(default_factory=lambda: f"session_{uuid4().hex}")
    status: AgentSessionStatus = AgentSessionStatus.INITIALIZED
    token_usage: dict[str, int] = field(default_factory=dict)
    latency_ms: float = 0
    cost: float = 0
    retries: int = 0
    artifacts_generated: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None

    def start(self) -> None:
        self.status = AgentSessionStatus.RUNNING

    def finish(self, status: AgentSessionStatus, artifacts: list[Artifact] | None = None) -> None:
        self.status = status
        self.finished_at = datetime.now(timezone.utc)
        for artifact in artifacts or []:
            self.artifacts_generated.append(artifact.id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "workflow_id": self.workflow_id,
            "active_step": self.active_step,
            "provider": self.provider,
            "model": self.model,
            "status": self.status.value,
            "token_usage": self.token_usage,
            "latency_ms": self.latency_ms,
            "cost": self.cost,
            "retries": self.retries,
            "artifacts_generated": list(self.artifacts_generated),
            "metadata": self.metadata,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }

