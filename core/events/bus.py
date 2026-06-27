from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable
from uuid import uuid4


class EventType(str, Enum):
    TASK_CREATED = "TaskCreated"
    TASK_SCHEDULED = "TaskScheduled"
    TASK_STARTED = "TaskStarted"
    TASK_COMPLETED = "TaskCompleted"
    TASK_FAILED = "TaskFailed"
    WORKFLOW_STARTED = "WorkflowStarted"
    WORKFLOW_FINISHED = "WorkflowFinished"
    PLANNING_STARTED = "PlanningStarted"
    PLANNING_COMPLETED = "PlanningCompleted"
    SKILL_STARTED = "SkillStarted"
    SKILL_FINISHED = "SkillFinished"
    VERIFICATION_STARTED = "VerificationStarted"
    VERIFICATION_PASSED = "VerificationPassed"
    VERIFICATION_FAILED = "VerificationFailed"
    VERIFICATION_EXECUTED = "VerificationExecuted"
    TESTS_PASSED = "TestsPassed"
    TESTS_FAILED = "TestsFailed"
    RETRY_REQUESTED = "RetryRequested"
    DECISION_MADE = "DecisionMade"
    STATE_TRANSITIONED = "StateTransitioned"
    RUNTIME_STARTED = "RuntimeStarted"
    RUNTIME_FINISHED = "RuntimeFinished"
    COMMAND_STARTED = "CommandStarted"
    COMMAND_FINISHED = "CommandFinished"
    COMMAND_CANCELLED = "CommandCancelled"
    WORKTREE_CREATED = "WorktreeCreated"
    WORKTREE_DESTROYED = "WorktreeDestroyed"
    RECOVERY_REQUESTED = "RecoveryRequested"
    RECOVERY_FINISHED = "RecoveryFinished"
    AGENT_STARTED = "AgentStarted"
    AGENT_FINISHED = "AgentFinished"
    MEMORY_UPDATED = "MemoryUpdated"


@dataclass(frozen=True, slots=True)
class Event:
    type: EventType
    task_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: f"event_{uuid4().hex}")
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


Subscriber = Callable[[Event], None]


class EventBus(ABC):
    @abstractmethod
    def publish(self, event: Event) -> None:
        raise NotImplementedError

    @abstractmethod
    def subscribe(self, subscriber: Subscriber) -> None:
        raise NotImplementedError


class InMemoryEventBus(EventBus):
    def __init__(self) -> None:
        self._events: list[Event] = []
        self._subscribers: list[Subscriber] = []

    def publish(self, event: Event) -> None:
        self._events.append(event)
        for subscriber in list(self._subscribers):
            subscriber(event)

    def subscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.append(subscriber)

    def list(self) -> list[Event]:
        return list(self._events)
