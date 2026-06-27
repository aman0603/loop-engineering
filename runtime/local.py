from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from core.events import Event, EventType
from core.execution import ExecutionContext
from runtime.command import CommandResult, CommandRunner, CommandSpec


@dataclass(slots=True)
class RuntimeResult:
    result: CommandResult

    @property
    def success(self) -> bool:
        return self.result.success


class Runtime(ABC):
    name: str

    @abstractmethod
    def execute(self, spec: CommandSpec, context: ExecutionContext) -> RuntimeResult:
        raise NotImplementedError


class LocalRuntime(Runtime):
    name = "runtime.local"

    def __init__(self, runner: CommandRunner | None = None, working_directory: Path | None = None) -> None:
        self.runner = runner or CommandRunner()
        self.working_directory = working_directory

    def execute(self, spec: CommandSpec, context: ExecutionContext) -> RuntimeResult:
        cwd = spec.cwd or self.working_directory
        runtime_spec = CommandSpec(
            args=spec.args,
            cwd=cwd,
            env=spec.env,
            timeout_seconds=spec.timeout_seconds or context.configuration.command_timeout_seconds,
            retries=spec.retries if spec.retries else context.configuration.command_retries,
            stream_output=spec.stream_output,
            name=spec.name,
        )
        context.emit(Event(EventType.RUNTIME_STARTED, context.task.id, {"runtime": self.name, "cwd": str(cwd) if cwd else None}))
        result = self.runner.run(runtime_spec, context)
        context.emit(
            Event(
                EventType.RUNTIME_FINISHED,
                context.task.id,
                {"runtime": self.name, "success": result.success, "exit_code": result.exit_code},
            )
        )
        return RuntimeResult(result=result)

