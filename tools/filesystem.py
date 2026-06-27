from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from core.artifacts import Artifact, ArtifactType, PatchArtifact, RuntimeLogArtifact
from core.execution import ExecutionContext
from tools.base import Tool, ToolResult


@dataclass(frozen=True, slots=True)
class WriteFileRequest:
    path: str | Path
    content: str
    create_parents: bool = True


@dataclass(frozen=True, slots=True)
class PatchFileRequest:
    path: str | Path
    old: str
    new: str
    count: int = -1


@dataclass(frozen=True, slots=True)
class DeleteFileRequest:
    path: str | Path
    missing_ok: bool = False


class FileSystemTool(Tool):
    name = "filesystem"

    def execute(self, context: ExecutionContext, request=None) -> ToolResult:
        return ToolResult(success=False, errors=["use a specific filesystem operation method"])

    def read_file(self, context: ExecutionContext, path: str | Path) -> ToolResult:
        target = self._resolve(context, path)
        content = target.read_text(encoding="utf-8")
        artifact = RuntimeLogArtifact(self.name, {"operation": "read_file", "path": str(target)})
        return ToolResult(success=True, output={"path": str(target), "content": content}, artifacts=[artifact])

    def write_file(self, context: ExecutionContext, request: WriteFileRequest) -> ToolResult:
        target = self._resolve(context, request.path)
        if request.create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(request.content, encoding="utf-8")
        artifact = Artifact(ArtifactType.DOCUMENTATION, self.name, request.content, {"path": str(target)})
        return ToolResult(success=True, output={"path": str(target)}, artifacts=[artifact])

    def patch_file(self, context: ExecutionContext, request: PatchFileRequest) -> ToolResult:
        target = self._resolve(context, request.path)
        content = target.read_text(encoding="utf-8")
        if request.old not in content:
            return ToolResult(success=False, errors=[f"patch target not found in {target}"])
        patched = content.replace(request.old, request.new, request.count)
        target.write_text(patched, encoding="utf-8")
        return ToolResult(
            success=True,
            output={"path": str(target)},
            artifacts=[PatchArtifact(self.name, {"path": str(target), "old": request.old, "new": request.new})],
        )

    def delete_file(self, context: ExecutionContext, request: DeleteFileRequest) -> ToolResult:
        target = self._resolve(context, request.path)
        try:
            target.unlink()
        except FileNotFoundError:
            if not request.missing_ok:
                raise
        artifact = RuntimeLogArtifact(self.name, {"operation": "delete_file", "path": str(target)})
        return ToolResult(success=True, output={"path": str(target)}, artifacts=[artifact])

    def list_directory(self, context: ExecutionContext, path: str | Path = ".") -> ToolResult:
        target = self._resolve(context, path)
        entries = sorted(item.name for item in target.iterdir())
        artifact = RuntimeLogArtifact(self.name, {"operation": "list_directory", "path": str(target), "entries": entries})
        return ToolResult(success=True, output={"path": str(target), "entries": entries}, artifacts=[artifact])

    def search_files(self, context: ExecutionContext, pattern: str, root: str | Path = ".") -> ToolResult:
        target = self._resolve(context, root)
        matches: list[str] = []
        for dirpath, _, filenames in os.walk(target):
            for filename in filenames:
                file_path = Path(dirpath) / filename
                try:
                    if pattern in file_path.read_text(encoding="utf-8"):
                        matches.append(str(file_path))
                except UnicodeDecodeError:
                    continue
        artifact = RuntimeLogArtifact(self.name, {"operation": "search_files", "pattern": pattern, "matches": matches})
        return ToolResult(success=True, output={"matches": matches}, artifacts=[artifact])

    def _resolve(self, context: ExecutionContext, path: str | Path) -> Path:
        base = context.working_directory or context.worktree_path or Path.cwd()
        target = Path(path)
        if not target.is_absolute():
            target = base / target
        resolved = target.resolve()
        base_resolved = base.resolve()
        if base_resolved not in resolved.parents and resolved != base_resolved:
            raise ValueError(f"filesystem operation escapes working directory: {resolved}")
        return resolved

