from __future__ import annotations

from core.artifacts import TestArtifact
from core.execution import ExecutionContext
from runtime import CommandSpec, LocalRuntime, Runtime
from tools.base import Tool, ToolResult


class TestTool(Tool):
    name = "test"
    __test__ = False

    def __init__(self, runtime: Runtime | None = None) -> None:
        self.runtime = runtime or LocalRuntime()

    def execute(self, context: ExecutionContext, request: list[str] | None = None) -> ToolResult:
        args = request or ["python3", "-m", "pytest"]
        result = self.runtime.execute(CommandSpec(args=args, cwd=context.working_directory, name="test"), context).result
        return ToolResult(
            success=result.success,
            output={"command": result.to_dict()},
            artifacts=[TestArtifact(self.name, result.to_dict())],
            errors=[] if result.success else [result.stderr or result.stdout],
            metrics={"test.duration_ms": result.duration_ms},
        )
