from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from core.artifacts import Artifact, ArtifactStore, ArtifactType, LogArtifact
from core.config import ExecutionConfig
from core.events import Event, EventBus, InMemoryEventBus
from core.task_manager.models import Task


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    name: str
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CancellationToken:
    cancelled: bool = False
    reason: str | None = None

    def cancel(self, reason: str | None = None) -> None:
        self.cancelled = True
        self.reason = reason


@dataclass(slots=True)
class MetricsCollector:
    counters: dict[str, int] = field(default_factory=dict)
    values: dict[str, Any] = field(default_factory=dict)
    timings_ms: dict[str, float] = field(default_factory=dict)

    def increment(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + amount

    def set(self, name: str, value: Any) -> None:
        self.values[name] = value

    def record_timing(self, name: str, duration_ms: float) -> None:
        self.timings_ms[name] = duration_ms

    def snapshot(self) -> dict[str, Any]:
        return {
            "counters": dict(self.counters),
            "values": dict(self.values),
            "timings_ms": dict(self.timings_ms),
        }


@dataclass(slots=True)
class ExecutionLogger:
    entries: list[dict[str, Any]] = field(default_factory=list)

    def log(self, source: str, message: str, **metadata: Any) -> None:
        self.entries.append(
            {
                "source": source,
                "message": message,
                "metadata": metadata,
                "timestamp": utc_now().isoformat(),
            }
        )


@dataclass
class ExecutionContext:
    task: Task
    configuration: ExecutionConfig = field(default_factory=ExecutionConfig)
    execution_metadata: dict[str, Any] = field(default_factory=dict)
    current_workflow: str | None = None
    current_agent: str | None = None
    current_skill: str | None = None
    retry_count: int = 0
    logger: ExecutionLogger = field(default_factory=ExecutionLogger)
    metrics: MetricsCollector = field(default_factory=MetricsCollector)
    event_bus: EventBus = field(default_factory=InMemoryEventBus)
    artifact_store: ArtifactStore = field(default_factory=ArtifactStore)
    cancellation_token: CancellationToken = field(default_factory=CancellationToken)
    runtime_variables: dict[str, Any] = field(default_factory=dict)
    feedback: list[Any] = field(default_factory=list)
    workflow_state: str | None = None
    state_transitions: list[dict[str, Any]] = field(default_factory=list)
    verification_results: list[Any] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    timeline: list[TimelineEntry] = field(default_factory=list)
    id: str = field(default_factory=lambda: f"exec_{uuid4().hex}")
    start_time: datetime = field(default_factory=utc_now)
    end_time: datetime | None = None

    @property
    def retry_limit(self) -> int:
        return min(self.configuration.retry_limit, self.task.max_attempts)

    @property
    def cancelled(self) -> bool:
        return self.cancellation_token.cancelled

    @property
    def artifacts(self) -> dict[str, Any]:
        """Compatibility view for legacy checks that read context.artifacts."""
        return self.artifact_store.compatibility_view()

    @property
    def metadata(self) -> dict[str, Any]:
        """Compatibility alias for legacy SkillContext metadata."""
        return self.execution_metadata

    def merge_artifacts(self, artifacts: dict[str, Any], producer: str = "legacy") -> None:
        for artifact_type, content in artifacts.items():
            if isinstance(content, Artifact):
                self.add_artifact(content)
            else:
                self.add_artifact_content(str(artifact_type), producer, content)

    def add_artifact(self, artifact: Artifact) -> Artifact:
        stored = self.artifact_store.add(artifact)
        self.metrics.increment("artifacts_produced")
        artifact_type = stored.type.value if isinstance(stored.type, ArtifactType) else stored.type
        self.record_timeline("artifact_produced", artifact_id=stored.id, type=artifact_type, producer=stored.producer)
        return stored

    def add_artifact_content(
        self,
        artifact_type: ArtifactType | str,
        producer: str,
        content: Any,
        **metadata: Any,
    ) -> Artifact:
        artifact = Artifact(artifact_type, producer, content, metadata)
        return self.add_artifact(artifact)

    def emit(self, event: Event) -> None:
        self.event_bus.publish(event)
        self.record_timeline(event.type.value, event_id=event.id, payload=event.payload)

    def log(self, source: str, message: str, **metadata: Any) -> None:
        self.logger.log(source, message, **metadata)
        self.task.add_log(source, message, **metadata)
        self.add_artifact(LogArtifact(source, {"message": message}, **metadata))

    def record_error(self, source: str, message: str, **metadata: Any) -> None:
        error = {"source": source, "message": message, "metadata": metadata, "timestamp": utc_now().isoformat()}
        self.errors.append(error)
        self.metrics.increment("errors")
        self.record_timeline("error", **error)

    def record_state_transition(self, from_state: str | None, to_state: str) -> None:
        transition = {
            "from": from_state,
            "to": to_state,
            "timestamp": utc_now().isoformat(),
        }
        self.state_transitions.append(transition)
        self.workflow_state = to_state
        self.metrics.increment("state_transitions")
        self.record_timeline("state_transition", **transition)

    def record_timeline(self, name: str, **metadata: Any) -> None:
        self.timeline.append(TimelineEntry(name=name, timestamp=utc_now(), metadata=metadata))

    def finish(self) -> None:
        self.end_time = utc_now()
        self.metrics.record_timing("execution_time_ms", self.execution_time_ms)
        self.task.metrics.update(self.metrics.snapshot())

    @property
    def execution_time_ms(self) -> float:
        end = self.end_time or utc_now()
        return (end - self.start_time).total_seconds() * 1000

    def observability_snapshot(self) -> dict[str, Any]:
        return {
            "execution_id": self.id,
            "task_id": self.task.id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "execution_time_ms": self.execution_time_ms,
            "retries": self.retry_count,
            "state_transitions": list(self.state_transitions),
            "events": [event.type.value for event in self.event_bus.list()] if hasattr(self.event_bus, "list") else [],
            "artifacts": [artifact.to_dict() for artifact in self.artifact_store.list()],
            "verification_results": [
                result.to_dict() if hasattr(result, "to_dict") else result
                for result in self.verification_results
            ],
            "errors": list(self.errors),
            "timeline": [
                {"name": entry.name, "timestamp": entry.timestamp.isoformat(), "metadata": entry.metadata}
                for entry in self.timeline
            ],
            "metrics": self.metrics.snapshot(),
        }

