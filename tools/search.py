from __future__ import annotations

from core.execution import ExecutionContext
from tools.base import Tool, ToolResult


class SearchTool(Tool):
    name = "search"

    def execute(self, context: ExecutionContext, request=None) -> ToolResult:
        return ToolResult(success=False, errors=["search tool is a Phase 2 placeholder"])

