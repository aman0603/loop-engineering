from __future__ import annotations

from pathlib import Path

from core.artifacts import DiffArtifact
from core.execution import ExecutionContext
from runtime import CommandSpec, LocalRuntime, Runtime
from tools.base import Tool, ToolResult


class GitTool(Tool):
    name = "git"

    def __init__(self, runtime: Runtime | None = None) -> None:
        self.runtime = runtime or LocalRuntime()

    def execute(self, context: ExecutionContext, request: list[str] | None = None) -> ToolResult:
        if request is None:
            return ToolResult(success=False, errors=["git args are required"])
        return self.run_git(context, request)

    def run_git(self, context: ExecutionContext, args: list[str], cwd: Path | None = None) -> ToolResult:
        result = self.runtime.execute(
            CommandSpec(args=["git", *args], cwd=cwd or context.working_directory, name="git"),
            context,
        ).result
        artifacts = []
        if args and args[0] == "diff":
            artifacts.append(DiffArtifact(self.name, result.stdout, args=args))
        return ToolResult(
            success=result.success,
            output={"command": result.to_dict()},
            artifacts=artifacts,
            errors=[] if result.success else [result.stderr],
            metrics={"git.duration_ms": result.duration_ms},
        )

