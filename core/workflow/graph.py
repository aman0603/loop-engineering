from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol

from core.events import Event, EventType
from core.execution import ExecutionContext


class WorkflowStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class WorkflowContext(ExecutionContext):
    """Backward-compatible name for the Phase 1 workflow context."""


@dataclass(slots=True)
class NodeResult:
    context: ExecutionContext
    next_node: str | None = None
    completed: bool = False
    failed: bool = False
    pause_requested: bool = False


class WorkflowNode(Protocol):
    name: str

    def run(self, context: ExecutionContext) -> NodeResult:
        ...


class FunctionNode:
    def __init__(self, name: str, handler: Callable[[ExecutionContext], NodeResult]) -> None:
        self.name = name
        self._handler = handler

    def run(self, context: ExecutionContext) -> NodeResult:
        return self._handler(context)

    def execute(self, context: ExecutionContext) -> NodeResult:
        return self.run(context)


@dataclass(slots=True)
class WorkflowDefinition:
    name: str
    start_node: str
    nodes: dict[str, WorkflowNode]


@dataclass(slots=True)
class WorkflowExecution:
    definition: WorkflowDefinition
    context: ExecutionContext
    status: WorkflowStatus
    visited_nodes: list[str] = field(default_factory=list)


class WorkflowEngine:
    def run(self, definition: WorkflowDefinition, context: ExecutionContext, max_steps: int = 100) -> WorkflowExecution:
        current = definition.start_node
        visited: list[str] = []
        context.current_workflow = definition.name
        context.emit(Event(EventType.WORKFLOW_STARTED, context.task.id, {"workflow": definition.name}))

        for _ in range(max_steps):
            if context.cancelled:
                execution = WorkflowExecution(definition, context, WorkflowStatus.CANCELLED, visited)
                self._finish(context, definition, execution)
                return execution

            node = definition.nodes[current]
            visited.append(current)
            result = node.run(context)
            context = result.context

            if result.pause_requested:
                context.runtime_variables["paused"] = True
                execution = WorkflowExecution(definition, context, WorkflowStatus.PAUSED, visited)
                self._finish(context, definition, execution)
                return execution
            if result.failed:
                execution = WorkflowExecution(definition, context, WorkflowStatus.FAILED, visited)
                self._finish(context, definition, execution)
                return execution
            if result.completed:
                execution = WorkflowExecution(definition, context, WorkflowStatus.COMPLETED, visited)
                self._finish(context, definition, execution)
                return execution
            if result.next_node is None:
                raise RuntimeError(f"workflow node '{current}' did not declare a next node")
            if result.next_node not in definition.nodes:
                raise KeyError(f"workflow node '{result.next_node}' is not registered")
            current = result.next_node

        raise TimeoutError(f"workflow '{definition.name}' exceeded max_steps={max_steps}")

    def _finish(
        self,
        context: ExecutionContext,
        definition: WorkflowDefinition,
        execution: WorkflowExecution,
    ) -> None:
        context.finish()
        context.emit(
            Event(
                EventType.WORKFLOW_FINISHED,
                context.task.id,
                {
                    "workflow": definition.name,
                    "status": execution.status.value,
                    "visited_nodes": list(execution.visited_nodes),
                },
            )
        )
