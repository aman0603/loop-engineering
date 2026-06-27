from __future__ import annotations

import sys

from core.execution import ExecutionContext
from runtime import CommandSpec, LocalRuntime, Runtime
from tools.base import Tool, ToolResult


class PythonTool(Tool):
    name = "python"

    def __init__(self, runtime: Runtime | None = None, executable: str | None = None) -> None:
        self.runtime = runtime or LocalRuntime()
        self.executable = executable or sys.executable

    def execute(self, context: ExecutionContext, request: list[str] | str | None = None) -> ToolResult:
        if request is None:
            return ToolResult(success=False, errors=["python request is required"])
        args = [self.executable, "-c", request] if isinstance(request, str) else [self.executable, *request]
        result = self.runtime.execute(CommandSpec(args=args, cwd=context.working_directory, name="python"), context).result
        return ToolResult(
            success=result.success,
            output={"command": result.to_dict()},
            errors=[] if result.success else [result.stderr],
            metrics={"python.duration_ms": result.duration_ms},
        )

