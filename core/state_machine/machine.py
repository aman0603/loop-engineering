from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.events import Event, EventType
from core.execution import ExecutionContext
from core.task_manager.models import TaskStatus


class WorkflowState(str, Enum):
    NEW = "NEW"
    PLANNING = "PLANNING"
    IMPLEMENTING = "IMPLEMENTING"
    VERIFYING = "VERIFYING"
    FAILED = "FAILED"
    REPLANNING = "REPLANNING"
    DONE = "DONE"
    ABORTED = "ABORTED"


STATE_TO_TASK_STATUS = {
    WorkflowState.NEW: TaskStatus.NEW,
    WorkflowState.PLANNING: TaskStatus.PLANNING,
    WorkflowState.IMPLEMENTING: TaskStatus.EXECUTING,
    WorkflowState.VERIFYING: TaskStatus.VERIFYING,
    WorkflowState.FAILED: TaskStatus.FAILED,
    WorkflowState.REPLANNING: TaskStatus.REPLANNING,
    WorkflowState.DONE: TaskStatus.DONE,
    WorkflowState.ABORTED: TaskStatus.FAILED,
}


@dataclass(frozen=True, slots=True)
class StateTransition:
    source: WorkflowState
    target: WorkflowState
    event: str


class StateMachine:
    def __init__(self, transitions: list[StateTransition] | None = None) -> None:
        self.transitions = transitions or [
            StateTransition(WorkflowState.NEW, WorkflowState.PLANNING, "plan"),
            StateTransition(WorkflowState.PLANNING, WorkflowState.IMPLEMENTING, "implement"),
            StateTransition(WorkflowState.PLANNING, WorkflowState.FAILED, "fail"),
            StateTransition(WorkflowState.REPLANNING, WorkflowState.IMPLEMENTING, "implement"),
            StateTransition(WorkflowState.REPLANNING, WorkflowState.FAILED, "fail"),
            StateTransition(WorkflowState.IMPLEMENTING, WorkflowState.VERIFYING, "verify"),
            StateTransition(WorkflowState.IMPLEMENTING, WorkflowState.FAILED, "fail"),
            StateTransition(WorkflowState.VERIFYING, WorkflowState.DONE, "complete"),
            StateTransition(WorkflowState.VERIFYING, WorkflowState.FAILED, "fail"),
            StateTransition(WorkflowState.FAILED, WorkflowState.REPLANNING, "retry"),
            StateTransition(WorkflowState.FAILED, WorkflowState.ABORTED, "abort"),
        ]

    def can_transition(self, source: WorkflowState | str | None, target: WorkflowState | str) -> bool:
        source_state = WorkflowState(source or WorkflowState.NEW.value)
        target_state = WorkflowState(target)
        return any(item.source == source_state and item.target == target_state for item in self.transitions)

    def transition(self, context: ExecutionContext, target: WorkflowState | str) -> None:
        source = WorkflowState(context.workflow_state or WorkflowState.NEW.value)
        target_state = WorkflowState(target)
        if source == target_state:
            return
        if not self.can_transition(source, target_state):
            raise ValueError(f"invalid workflow transition: {source.value} -> {target_state.value}")

        context.record_state_transition(source.value, target_state.value)
        task_status = STATE_TO_TASK_STATUS[target_state]
        if context.task.status != task_status:
            context.task.transition_to(task_status)
        context.emit(
            Event(
                EventType.STATE_TRANSITIONED,
                context.task.id,
                {"from": source.value, "to": target_state.value},
            )
        )

    def transition_for_event(self, context: ExecutionContext, event: str) -> WorkflowState:
        source = WorkflowState(context.workflow_state or WorkflowState.NEW.value)
        for transition in self.transitions:
            if transition.source == source and transition.event == event:
                self.transition(context, transition.target)
                return transition.target
        raise ValueError(f"no transition for state={source.value} event={event}")
