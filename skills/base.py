from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.artifacts import Artifact
from core.execution import ExecutionContext
from core.task_manager.models import Task


@dataclass(slots=True)
class SkillContext:
    workspace: Path | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)
    feedback: list[Any] = field(default_factory=list)
    memory: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def merge_artifacts(self, artifacts: dict[str, Any]) -> None:
        self.artifacts.update(artifacts)


@dataclass(slots=True)
class SkillResult:
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    artifacts: list[Artifact] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class Skill(ABC):
    name: str

    def initialize(self, context: ExecutionContext | SkillContext) -> None:
        return None

    @abstractmethod
    def run(self, context: ExecutionContext) -> SkillResult:
        raise NotImplementedError

    def execute(self, context: ExecutionContext) -> SkillResult:
        self.initialize(context)
        try:
            result = self._call_run(context)
            result = self._call_validate(context, result)
        finally:
            self.cleanup(context)
        return result

    def validate(self, context: ExecutionContext, result: SkillResult) -> SkillResult:
        return result

    def cleanup(self, context: ExecutionContext | SkillContext) -> None:
        return None

    def _call_run(self, context: ExecutionContext) -> SkillResult:
        parameter_count = len(inspect.signature(self.run).parameters)
        if parameter_count == 1:
            return self.run(context)
        if parameter_count == 2:
            return self.run(context.task, context)  # type: ignore[misc]
        raise TypeError(f"unsupported run signature for skill '{self.name}'")

    def _call_validate(self, context: ExecutionContext, result: SkillResult) -> SkillResult:
        parameter_count = len(inspect.signature(self.validate).parameters)
        if parameter_count == 2:
            return self.validate(context, result)
        if parameter_count == 3:
            return self.validate(context.task, context, result)  # type: ignore[misc]
        raise TypeError(f"unsupported validate signature for skill '{self.name}'")


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        if not skill.name:
            raise ValueError("skill name is required")
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill:
        try:
            return self._skills[name]
        except KeyError as exc:
            raise KeyError(f"skill not registered: {name}") from exc

    def list(self) -> list[Skill]:
        return list(self._skills.values())
