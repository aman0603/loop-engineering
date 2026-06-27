from __future__ import annotations

from core.execution import ExecutionContext
from tools.base import Tool, ToolResult


class HTTPTool(Tool):
    name = "http"

    def execute(self, context: ExecutionContext, request=None) -> ToolResult:
        return ToolResult(success=False, errors=["http tool is a Phase 2 placeholder"])

