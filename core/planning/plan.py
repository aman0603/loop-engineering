from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class PlanStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


def plan_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 1
    backoff_seconds: float = 0
    retry_on: list[str] = field(default_factory=lambda: ["FAILED"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_attempts": self.max_attempts,
            "backoff_seconds": self.backoff_seconds,
            "retry_on": list(self.retry_on),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RetryPolicy":
        return cls(
            max_attempts=int(data.get("max_attempts", 1)),
            backoff_seconds=float(data.get("backoff_seconds", 0)),
            retry_on=list(data.get("retry_on", ["FAILED"])),
        )


@dataclass(slots=True)
class ExecutionStep:
    description: str
    required_skill: str | None = None
    required_tools: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    timeout: float | None = None
    expected_artifacts: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: plan_id("step"))
    required_capability: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    status: PlanStatus = PlanStatus.PENDING
    attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "required_skill": self.required_skill,
            "required_tools": list(self.required_tools),
            "dependencies": list(self.dependencies),
            "success_criteria": list(self.success_criteria),
            "retry_policy": self.retry_policy.to_dict(),
            "timeout": self.timeout,
            "expected_artifacts": list(self.expected_artifacts),
            "required_capability": self.required_capability,
            "metadata": self.metadata,
            "status": self.status.value,
            "attempts": self.attempts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionStep":
        return cls(
            id=data["id"],
            description=data["description"],
            required_skill=data.get("required_skill"),
            required_tools=list(data.get("required_tools", [])),
            dependencies=list(data.get("dependencies", [])),
            success_criteria=list(data.get("success_criteria", [])),
            retry_policy=RetryPolicy.from_dict(data.get("retry_policy", {})),
            timeout=data.get("timeout"),
            expected_artifacts=list(data.get("expected_artifacts", [])),
            required_capability=data.get("required_capability"),
            metadata=dict(data.get("metadata", {})),
            status=PlanStatus(data.get("status", PlanStatus.PENDING.value)),
            attempts=int(data.get("attempts", 0)),
        )


@dataclass(slots=True)
class ExecutionPlan:
    task_id: str
    steps: list[ExecutionStep]
    id: str = field(default_factory=lambda: plan_id("plan"))
    revision: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validate()

    @property
    def step_map(self) -> dict[str, ExecutionStep]:
        return {step.id: step for step in self.steps}

    def validate(self) -> None:
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("execution plan contains duplicate step ids")
        known = set(ids)
        for step in self.steps:
            missing = set(step.dependencies) - known
            if missing:
                raise ValueError(f"step '{step.id}' depends on unknown steps: {sorted(missing)}")
        self.detect_cycles()

    def detect_cycles(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()
        steps = self.step_map

        def visit(step_id: str) -> None:
            if step_id in visited:
                return
            if step_id in visiting:
                raise ValueError(f"execution plan contains a cycle at step '{step_id}'")
            visiting.add(step_id)
            for dependency in steps[step_id].dependencies:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step in self.steps:
            visit(step.id)

    def topological_order(self) -> list[ExecutionStep]:
        remaining = {step.id: set(step.dependencies) for step in self.steps}
        ordered: list[ExecutionStep] = []
        completed: set[str] = set()
        steps = self.step_map

        while remaining:
            ready = sorted(step_id for step_id, deps in remaining.items() if deps <= completed)
            if not ready:
                raise ValueError("execution plan contains a cycle")
            for step_id in ready:
                ordered.append(steps[step_id])
                completed.add(step_id)
                remaining.pop(step_id)
        return ordered

    def ready_steps(self, completed_step_ids: set[str], blocked_step_ids: set[str] | None = None) -> list[ExecutionStep]:
        blocked = blocked_step_ids or set()
        return [
            step
            for step in self.steps
            if step.id not in completed_step_ids
            and step.id not in blocked
            and set(step.dependencies) <= completed_step_ids
        ]

    def parallel_groups(self) -> list[list[ExecutionStep]]:
        remaining = {step.id: set(step.dependencies) for step in self.steps}
        completed: set[str] = set()
        steps = self.step_map
        groups: list[list[ExecutionStep]] = []

        while remaining:
            ready = sorted(step_id for step_id, deps in remaining.items() if deps <= completed)
            if not ready:
                raise ValueError("execution plan contains a cycle")
            groups.append([steps[step_id] for step_id in ready])
            completed.update(ready)
            for step_id in ready:
                remaining.pop(step_id)
        return groups

    def descendants(self, step_id: str) -> set[str]:
        children: dict[str, list[str]] = {step.id: [] for step in self.steps}
        for step in self.steps:
            for dependency in step.dependencies:
                children[dependency].append(step.id)
        result: set[str] = set()
        stack = list(children.get(step_id, []))
        while stack:
            current = stack.pop()
            if current in result:
                continue
            result.add(current)
            stack.extend(children.get(current, []))
        return result

    def subtree(self, root_step_id: str) -> "ExecutionPlan":
        selected = {root_step_id, *self.descendants(root_step_id)}
        steps = []
        for step in self.steps:
            if step.id not in selected:
                continue
            data = step.to_dict()
            data["dependencies"] = [item for item in step.dependencies if item in selected]
            data["status"] = PlanStatus.PENDING.value
            data["attempts"] = 0
            steps.append(ExecutionStep.from_dict(data))
        return ExecutionPlan(
            task_id=self.task_id,
            steps=steps,
            revision=self.revision + 1,
            metadata={**self.metadata, "replanned_from": self.id, "subtree_root": root_step_id},
        )

    def critical_path(self) -> list[str]:
        steps = self.step_map
        memo: dict[str, tuple[int, list[str]]] = {}

        def best_path(step_id: str) -> tuple[int, list[str]]:
            if step_id in memo:
                return memo[step_id]
            dependency_paths = [best_path(dep) for dep in steps[step_id].dependencies]
            if dependency_paths:
                length, path = max(dependency_paths, key=lambda item: item[0])
                memo[step_id] = (length + 1, [*path, step_id])
            else:
                memo[step_id] = (1, [step_id])
            return memo[step_id]

        if not self.steps:
            return []
        return max((best_path(step.id) for step in self.steps), key=lambda item: item[0])[1]

    def metrics(self) -> dict[str, Any]:
        groups = self.parallel_groups()
        return {
            "workflow_depth": len(groups),
            "workflow_width": max((len(group) for group in groups), default=0),
            "parallelism": sum(1 for group in groups if len(group) > 1),
            "critical_path": self.critical_path(),
            "step_count": len(self.steps),
            "plan_revision": self.revision,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "revision": self.revision,
            "metadata": self.metadata,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionPlan":
        return cls(
            id=data["id"],
            task_id=data["task_id"],
            revision=int(data.get("revision", 1)),
            metadata=dict(data.get("metadata", {})),
            steps=[ExecutionStep.from_dict(item) for item in data.get("steps", [])],
        )

