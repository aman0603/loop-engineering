from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Generic, Protocol, TypeVar


class NamedComponent(Protocol):
    name: str


T = TypeVar("T", bound=NamedComponent)


@dataclass(slots=True)
class Registry(Generic[T]):
    component_label: str
    _components: dict[str, T] = field(default_factory=dict)

    def register(self, component: T) -> None:
        name = getattr(component, "name", None)
        if not name:
            raise ValueError(f"{self.component_label} name is required")
        self._components[str(name)] = component

    def get(self, name: str) -> T:
        try:
            return self._components[name]
        except KeyError as exc:
            raise KeyError(f"{self.component_label} not registered: {name}") from exc

    def list(self) -> list[T]:
        return list(self._components.values())

    def names(self) -> list[str]:
        return list(self._components)


class AgentRegistry(Registry):
    def __init__(self) -> None:
        super().__init__("agent")
        self._adapters: dict[str, object] = {}

    def register_adapter(self, adapter: object) -> None:
        name = getattr(adapter, "name", None)
        if not name:
            raise ValueError("agent adapter name is required")
        self._adapters[str(name)] = adapter

    def unregister_adapter(self, name: str) -> None:
        self._adapters.pop(name, None)

    def get_adapter(self, name: str) -> object:
        try:
            return self._adapters[name]
        except KeyError as exc:
            raise KeyError(f"agent adapter not registered: {name}") from exc

    def list_adapters(self) -> list[object]:
        return list(self._adapters.values())

    def adapter_names(self) -> list[str]:
        return list(self._adapters)

    def find_adapter_for_capability(self, capability: str, exclude: set[str] | None = None) -> object | None:
        excluded = exclude or set()
        for adapter in self._adapters.values():
            if getattr(adapter, "name") in excluded:
                continue
            health = adapter.health() if hasattr(adapter, "health") else None
            if health is not None and not health.available:
                continue
            capabilities = adapter.capabilities() if hasattr(adapter, "capabilities") else []
            if any(item.name == capability for item in capabilities):
                return adapter
        return None


class SkillRegistry(Registry):
    def __init__(self) -> None:
        super().__init__("skill")


class WorkflowRegistry(Registry):
    def __init__(self) -> None:
        super().__init__("workflow")
        self._workflow_specs: dict[str, object] = {}

    def register_workflow(self, workflow: object) -> None:
        if isinstance(workflow, dict):
            from core.workflow.library import EngineeringWorkflowDefinition

            workflow = EngineeringWorkflowDefinition.from_dict(workflow)
        name = getattr(workflow, "name", None)
        if not name:
            raise ValueError("workflow name is required")
        if hasattr(workflow, "validate"):
            workflow.validate()
        self._workflow_specs[str(name)] = workflow

    def unregister_workflow(self, name: str) -> None:
        self._workflow_specs.pop(name, None)

    def list_workflows(self) -> list[object]:
        return list(self._workflow_specs.values())

    def load_workflow(self, name: str) -> object:
        try:
            return self._workflow_specs[name]
        except KeyError as exc:
            raise KeyError(f"workflow definition not registered: {name}") from exc

    def validate_workflow(self, name: str) -> bool:
        workflow = self.load_workflow(name)
        if hasattr(workflow, "validate"):
            workflow.validate()
        return True

    def import_workflow(self, path: str | Path) -> object:
        from core.workflow.library import EngineeringWorkflowDefinition

        workflow = EngineeringWorkflowDefinition.load(path)
        self.register_workflow(workflow)
        return workflow

    def export_workflow(self, name: str, path: str | Path) -> None:
        workflow = self.load_workflow(name)
        if not hasattr(workflow, "export"):
            raise TypeError(f"workflow '{name}' is not exportable")
        workflow.export(path)


class VerifierRegistry(Registry):
    def __init__(self) -> None:
        super().__init__("verifier")


class ToolRegistry(Registry):
    def __init__(self) -> None:
        super().__init__("tool")
