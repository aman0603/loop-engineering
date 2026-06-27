from __future__ import annotations

from dataclasses import dataclass, field
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


class SkillRegistry(Registry):
    def __init__(self) -> None:
        super().__init__("skill")


class WorkflowRegistry(Registry):
    def __init__(self) -> None:
        super().__init__("workflow")


class VerifierRegistry(Registry):
    def __init__(self) -> None:
        super().__init__("verifier")


class ToolRegistry(Registry):
    def __init__(self) -> None:
        super().__init__("tool")

