from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.artifacts import Artifact
from core.planning import ExecutionPlan, ExecutionStep, RetryPolicy
from core.task_manager import Task


@dataclass(slots=True)
class WorkflowStepSpec:
    id: str
    description: str
    capability: str
    dependencies: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    timeout: float | None = None
    expected_artifacts: list[str] = field(default_factory=list)
    workflow: str | None = None
    approval: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "capability": self.capability,
            "dependencies": list(self.dependencies),
            "required_tools": list(self.required_tools),
            "retry_policy": self.retry_policy.to_dict(),
            "timeout": self.timeout,
            "expected_artifacts": list(self.expected_artifacts),
            "workflow": self.workflow,
            "approval": self.approval,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowStepSpec":
        return cls(
            id=data["id"],
            description=data["description"],
            capability=data.get("capability", data.get("required_capability", "coding")),
            dependencies=list(data.get("dependencies", [])),
            required_tools=list(data.get("required_tools", [])),
            retry_policy=RetryPolicy.from_dict(data.get("retry_policy", {})),
            timeout=data.get("timeout"),
            expected_artifacts=list(data.get("expected_artifacts", [])),
            workflow=data.get("workflow"),
            approval=bool(data.get("approval", False)),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(slots=True)
class EngineeringWorkflowDefinition:
    name: str
    metadata: dict[str, Any]
    steps: list[WorkflowStepSpec]
    parameters: dict[str, Any] = field(default_factory=dict)
    verification_stages: list[str] = field(default_factory=list)
    approval_stages: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)

    def validate(self) -> None:
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError(f"workflow '{self.name}' contains duplicate step ids")
        known = set(ids)
        for step in self.steps:
            missing = set(step.dependencies) - known
            if missing:
                raise ValueError(f"workflow '{self.name}' step '{step.id}' has unknown dependencies: {sorted(missing)}")
        self.to_execution_plan(Task(title="validation", description="validation", goal="validation"))

    def to_execution_plan(
        self,
        task: Task,
        parameters: dict[str, Any] | None = None,
        registry: Any | None = None,
    ) -> ExecutionPlan:
        merged_parameters = {**self.parameters, **(parameters or {})}
        expanded = self._expanded_steps(registry, merged_parameters)
        max_retries = int(merged_parameters.get("max_retries", task.max_attempts))
        steps = [
            ExecutionStep(
                id=step.id,
                description=self._render(step.description, task, merged_parameters),
                required_capability=step.capability,
                required_tools=step.required_tools,
                dependencies=step.dependencies,
                success_criteria=[self._render(item, task, merged_parameters) for item in step.metadata.get("success_criteria", [])],
                retry_policy=RetryPolicy(
                    max_attempts=step.retry_policy.max_attempts if step.retry_policy.max_attempts != 1 else max_retries,
                    backoff_seconds=step.retry_policy.backoff_seconds,
                    retry_on=step.retry_policy.retry_on,
                ),
                timeout=step.timeout,
                expected_artifacts=step.expected_artifacts or self._default_artifacts(step.capability),
                metadata={
                    **step.metadata,
                    "workflow": self.name,
                    "workflow_step": step.id,
                    "parameters": merged_parameters,
                    "approval_required": step.approval or step.id in self.approval_stages,
                },
            )
            for step in expanded
        ]
        return ExecutionPlan(
            task_id=task.id,
            steps=steps,
            metadata={
                "workflow": self.name,
                "workflow_metadata": self.metadata,
                "parameters": merged_parameters,
                "verification_stages": self.verification_stages,
                "approval_stages": self.approval_stages,
                "outputs": self.outputs,
            },
        )

    def _expanded_steps(self, registry: Any | None, parameters: dict[str, Any]) -> list[WorkflowStepSpec]:
        expanded: list[WorkflowStepSpec] = []
        for step in self.steps:
            if step.workflow and registry is not None:
                child = registry.load_workflow(step.workflow)
                child_steps = child._expanded_steps(registry, parameters)
                prefix = step.id
                child_ids = {item.id for item in child_steps}
                prefixed_ids = {f"{prefix}.{item.id}" for item in child_steps}
                for child_step in child_steps:
                    expanded.append(
                        WorkflowStepSpec(
                            id=f"{prefix}.{child_step.id}",
                            description=child_step.description,
                            capability=child_step.capability,
                            dependencies=[
                                f"{prefix}.{dep}" if dep in {item.id for item in child_steps} else dep
                                for dep in child_step.dependencies
                            ] or list(step.dependencies),
                            required_tools=child_step.required_tools,
                            retry_policy=child_step.retry_policy,
                            timeout=child_step.timeout,
                            expected_artifacts=child_step.expected_artifacts,
                            workflow=child_step.workflow,
                            approval=child_step.approval,
                            metadata={**child_step.metadata, "composed_from": step.workflow},
                        )
                    )
                dependents = {
                    dependency
                    for child_step in child_steps
                    for dependency in child_step.dependencies
                }
                leaf_ids = [f"{prefix}.{item.id}" for item in child_steps if item.id not in dependents]
                expanded.append(
                    WorkflowStepSpec(
                        id=step.id,
                        description=step.description,
                        capability=step.capability,
                        dependencies=leaf_ids or list(step.dependencies),
                        required_tools=step.required_tools,
                        retry_policy=step.retry_policy,
                        timeout=step.timeout,
                        expected_artifacts=step.expected_artifacts or ["log"],
                        approval=step.approval,
                        metadata={**step.metadata, "composed_workflow": step.workflow, "child_steps": sorted(prefixed_ids)},
                    )
                )
            else:
                expanded.append(step)
        return expanded

    def visualization_data(self, plan: ExecutionPlan, execution_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        edges = [
            {"from": dependency, "to": step.id}
            for step in plan.steps
            for dependency in step.dependencies
        ]
        artifacts = (execution_snapshot or {}).get("artifacts", [])
        return {
            "workflow": self.name,
            "dag": {"nodes": [step.to_dict() for step in plan.steps], "edges": edges},
            "timeline": (execution_snapshot or {}).get("timeline", []),
            "state_transitions": (execution_snapshot or {}).get("state_transitions", []),
            "artifact_graph": {
                "artifacts": artifacts,
                "edges": [
                    {"from": artifact.get("producer"), "to": artifact.get("id"), "type": artifact.get("type")}
                    for artifact in artifacts
                ],
            },
            "metrics": plan.metrics(),
        }

    def visualization_artifact(self, plan: ExecutionPlan, execution_snapshot: dict[str, Any] | None = None) -> Artifact:
        return Artifact("workflow_visualization", "workflow.library", self.visualization_data(plan, execution_snapshot))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "metadata": self.metadata,
            "parameters": self.parameters,
            "dependencies": list(self.dependencies),
            "verification_stages": list(self.verification_stages),
            "approval_stages": list(self.approval_stages),
            "outputs": list(self.outputs),
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EngineeringWorkflowDefinition":
        return cls(
            name=data["name"],
            metadata=dict(data.get("metadata", {})),
            parameters=dict(data.get("parameters", {})),
            dependencies=list(data.get("dependencies", [])),
            verification_stages=list(data.get("verification_stages", [])),
            approval_stages=list(data.get("approval_stages", [])),
            outputs=list(data.get("outputs", [])),
            steps=[WorkflowStepSpec.from_dict(item) for item in data.get("steps", [])],
        )

    @classmethod
    def from_json(cls, content: str) -> "EngineeringWorkflowDefinition":
        return cls.from_dict(json.loads(content))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_yaml(cls, content: str) -> "EngineeringWorkflowDefinition":
        return cls.from_dict(_parse_simple_yaml(content))

    def to_yaml(self) -> str:
        return _dump_simple_yaml(self.to_dict())

    @classmethod
    def load(cls, path: str | Path) -> "EngineeringWorkflowDefinition":
        file_path = Path(path)
        content = file_path.read_text(encoding="utf-8")
        if file_path.suffix.lower() in {".yaml", ".yml"}:
            return cls.from_yaml(content)
        return cls.from_json(content)

    def export(self, path: str | Path) -> None:
        file_path = Path(path)
        if file_path.suffix.lower() in {".yaml", ".yml"}:
            file_path.write_text(self.to_yaml(), encoding="utf-8")
        else:
            file_path.write_text(self.to_json(), encoding="utf-8")

    def _render(self, value: str, task: Task, parameters: dict[str, Any]) -> str:
        rendered = value.replace("{goal}", task.goal).replace("{title}", task.title)
        for key, parameter_value in parameters.items():
            rendered = rendered.replace("{" + key + "}", str(parameter_value))
        return rendered

    def _default_artifacts(self, capability: str) -> list[str]:
        return {
            "planning": ["plan"],
            "architecture": ["documentation"],
            "coding": ["implementation"],
            "debugging": ["patch"],
            "testing": ["test"],
            "review": ["review"],
            "documentation": ["documentation"],
            "benchmark": ["build"],
            "security": ["review"],
            "analysis": ["documentation"],
            "refactoring": ["patch"],
        }.get(capability, ["log"])


def _parse_simple_yaml(content: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore

        return yaml.safe_load(content)
    except Exception:
        return json.loads(content)


def _dump_simple_yaml(data: dict[str, Any]) -> str:
    try:
        import yaml  # type: ignore

        return yaml.safe_dump(data, sort_keys=True)
    except Exception:
        return json.dumps(data, indent=2, sort_keys=True)
