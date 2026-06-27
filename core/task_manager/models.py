from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_task_id() -> str:
    return f"task_{uuid4().hex}"


class TaskStatus(str, Enum):
    NEW = "NEW"
    PLANNING = "PLANNING"
    READY = "READY"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    FAILED = "FAILED"
    REPLANNING = "REPLANNING"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class Priority(IntEnum):
    CRITICAL = 0
    HIGH = 10
    NORMAL = 50
    LOW = 100


class VerificationOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.NEW: {TaskStatus.PLANNING, TaskStatus.READY, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.PLANNING: {TaskStatus.READY, TaskStatus.EXECUTING, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.READY: {TaskStatus.EXECUTING, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.EXECUTING: {TaskStatus.VERIFYING, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.VERIFYING: {
        TaskStatus.DONE,
        TaskStatus.FAILED,
        TaskStatus.REPLANNING,
        TaskStatus.CANCELLED,
    },
    TaskStatus.FAILED: {TaskStatus.REPLANNING, TaskStatus.CANCELLED},
    TaskStatus.REPLANNING: {TaskStatus.PLANNING, TaskStatus.EXECUTING, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.DONE: set(),
    TaskStatus.CANCELLED: set(),
}


@dataclass(slots=True)
class ExecutionLog:
    source: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "message": self.message,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionLog":
        return cls(
            source=data["source"],
            message=data["message"],
            metadata=dict(data.get("metadata", {})),
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )


@dataclass(slots=True)
class VerificationResult:
    name: str
    outcome: VerificationOutcome
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime = field(default_factory=utc_now)

    @property
    def passed(self) -> bool:
        return self.outcome == VerificationOutcome.PASSED

    @property
    def duration_ms(self) -> float:
        return (self.finished_at - self.started_at).total_seconds() * 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "outcome": self.outcome.value,
            "summary": self.summary,
            "details": self.details,
            "metrics": self.metrics,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VerificationResult":
        return cls(
            name=data["name"],
            outcome=VerificationOutcome(data["outcome"]),
            summary=data["summary"],
            details=dict(data.get("details", {})),
            metrics=dict(data.get("metrics", {})),
            started_at=datetime.fromisoformat(data["started_at"]),
            finished_at=datetime.fromisoformat(data["finished_at"]),
        )


@dataclass(slots=True)
class Task:
    title: str
    description: str
    goal: str
    acceptance_criteria: list[str] = field(default_factory=list)
    id: str = field(default_factory=new_task_id)
    priority: int = int(Priority.NORMAL)
    dependencies: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.NEW
    attempts: int = 0
    max_attempts: int = 3
    assigned_agent: str | None = None
    execution_logs: list[ExecutionLog] = field(default_factory=list)
    verification_results: list[VerificationResult] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def transition_to(self, status: TaskStatus) -> None:
        if status == self.status:
            return
        allowed = ALLOWED_TRANSITIONS[self.status]
        if status not in allowed:
            raise ValueError(f"invalid task transition: {self.status.value} -> {status.value}")
        self.status = status
        self.updated_at = utc_now()

    def add_log(self, source: str, message: str, **metadata: Any) -> None:
        self.execution_logs.append(ExecutionLog(source=source, message=message, metadata=metadata))
        self.updated_at = utc_now()

    def record_verification(self, result: VerificationResult) -> None:
        self.verification_results.append(result)
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "goal": self.goal,
            "acceptance_criteria": list(self.acceptance_criteria),
            "priority": self.priority,
            "dependencies": list(self.dependencies),
            "status": self.status.value,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "assigned_agent": self.assigned_agent,
            "execution_logs": [log.to_dict() for log in self.execution_logs],
            "verification_results": [result.to_dict() for result in self.verification_results],
            "metrics": self.metrics,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            goal=data["goal"],
            acceptance_criteria=list(data.get("acceptance_criteria", [])),
            priority=int(data.get("priority", int(Priority.NORMAL))),
            dependencies=list(data.get("dependencies", [])),
            status=TaskStatus(data.get("status", TaskStatus.NEW.value)),
            attempts=int(data.get("attempts", 0)),
            max_attempts=int(data.get("max_attempts", 3)),
            assigned_agent=data.get("assigned_agent"),
            execution_logs=[ExecutionLog.from_dict(item) for item in data.get("execution_logs", [])],
            verification_results=[
                VerificationResult.from_dict(item) for item in data.get("verification_results", [])
            ],
            metrics=dict(data.get("metrics", {})),
            metadata=dict(data.get("metadata", {})),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )
