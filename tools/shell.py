from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.artifacts import CommandArtifact
from core.execution import ExecutionContext
from runtime import CommandSpec, LocalRuntime, Runtime
from tools.base import Tool, ToolResult


@dataclass(frozen=True, slots=True)
class ShellRequest:
    args: list[str]
    cwd: Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float | None = None
    retries: int = 0
    name: str | None = None


class ShellTool(Tool):
    name = "shell"

    def __init__(self, runtime: Runtime | None = None) -> None:
        self.runtime = runtime or LocalRuntime()

    def execute(self, context: ExecutionContext, request: ShellRequest | list[str] | None = None) -> ToolResult:
        if request is None:
            return ToolResult(success=False, errors=["shell request is required"])
        if isinstance(request, list):
            request = ShellRequest(args=request)
        cwd = request.cwd or context.working_directory
        result = self.runtime.execute(
            CommandSpec(
                args=request.args,
                cwd=cwd,
                env=request.env,
                timeout_seconds=request.timeout_seconds,
                retries=request.retries,
                name=request.name or "shell",
            ),
            context,
        ).result
        return ToolResult(
            success=result.success,
            output={"command": result.to_dict()},
            artifacts=[CommandArtifact(self.name, result.to_dict())],
            errors=[] if result.success else [result.stderr or f"command failed: {result.exit_code}"],
            metrics={"shell.duration_ms": result.duration_ms},
        )

