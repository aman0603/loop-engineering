from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.artifacts import DiffArtifact, RuntimeLogArtifact
from core.events import Event, EventType
from core.execution import ExecutionContext
from runtime import CommandSpec, LocalRuntime, Runtime


@dataclass(frozen=True, slots=True)
class Worktree:
    path: Path
    branch: str
    repository: Path


class WorktreeManager:
    name = "worktree.manager"

    def __init__(
        self,
        repository: Path | str,
        root: Path | str | None = None,
        runtime: Runtime | None = None,
    ) -> None:
        self.repository = Path(repository).resolve()
        self.root = (
            Path(root).resolve()
            if root
            else Path(tempfile.gettempdir()) / "loop-engineering-worktrees" / self.repository.name
        )
        self.runtime = runtime or LocalRuntime()

    def create_worktree(
        self,
        context: ExecutionContext,
        branch: str | None = None,
        base_ref: str = "HEAD",
    ) -> Worktree:
        task_safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in context.task.id)
        branch_name = branch or f"loop/{task_safe}"
        path = self.root / task_safe
        self.root.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self.cleanup_worktree(context, Worktree(path=path, branch=branch_name, repository=self.repository), force=True)
        result = self.runtime.execute(
            CommandSpec(
                args=["git", "worktree", "add", "-B", branch_name, str(path), base_ref],
                cwd=self.repository,
                name="worktree.add",
            ),
            context,
        ).result
        if not result.success:
            raise RuntimeError(result.stderr or result.stdout)
        context.worktree_path = path
        context.working_directory = path
        context.runtime_variables["working_directory"] = str(path)
        worktree = Worktree(path=path, branch=branch_name, repository=self.repository)
        context.add_artifact(RuntimeLogArtifact(self.name, {"operation": "create_worktree", "path": str(path), "branch": branch_name}))
        context.emit(Event(EventType.WORKTREE_CREATED, context.task.id, {"path": str(path), "branch": branch_name}))
        return worktree

    def checkout_branch(self, context: ExecutionContext, worktree: Worktree, branch: str) -> None:
        result = self.runtime.execute(
            CommandSpec(args=["git", "checkout", branch], cwd=worktree.path, name="worktree.checkout"),
            context,
        ).result
        if not result.success:
            raise RuntimeError(result.stderr or result.stdout)

    def is_dirty(self, context: ExecutionContext, worktree: Worktree) -> bool:
        result = self.runtime.execute(
            CommandSpec(args=["git", "status", "--porcelain"], cwd=worktree.path, name="worktree.status"),
            context,
        ).result
        if not result.success:
            raise RuntimeError(result.stderr or result.stdout)
        return bool(result.stdout.strip())

    def commit_changes(self, context: ExecutionContext, worktree: Worktree, message: str) -> str | None:
        add = self.runtime.execute(CommandSpec(args=["git", "add", "-A"], cwd=worktree.path, name="worktree.add_all"), context).result
        if not add.success:
            raise RuntimeError(add.stderr or add.stdout)
        if not self.is_dirty(context, worktree):
            return None
        commit = self.runtime.execute(
            CommandSpec(args=["git", "commit", "-m", message], cwd=worktree.path, name="worktree.commit"),
            context,
        ).result
        if not commit.success:
            raise RuntimeError(commit.stderr or commit.stdout)
        rev = self.runtime.execute(
            CommandSpec(args=["git", "rev-parse", "HEAD"], cwd=worktree.path, name="worktree.rev_parse"),
            context,
        ).result
        sha = rev.stdout.strip() if rev.success else None
        context.add_artifact(RuntimeLogArtifact(self.name, {"operation": "commit", "sha": sha, "message": message}))
        return sha

    def rollback_changes(self, context: ExecutionContext, worktree: Worktree) -> None:
        diff = self.runtime.execute(CommandSpec(args=["git", "diff"], cwd=worktree.path, name="worktree.diff"), context).result
        if diff.stdout:
            context.add_artifact(DiffArtifact(self.name, diff.stdout, operation="rollback"))
        reset = self.runtime.execute(
            CommandSpec(args=["git", "reset", "--hard"], cwd=worktree.path, name="worktree.reset"),
            context,
        ).result
        clean = self.runtime.execute(
            CommandSpec(args=["git", "clean", "-fd"], cwd=worktree.path, name="worktree.clean"),
            context,
        ).result
        if not reset.success or not clean.success:
            raise RuntimeError(reset.stderr or clean.stderr)
        context.add_artifact(RuntimeLogArtifact(self.name, {"operation": "rollback", "path": str(worktree.path)}))

    def cleanup_worktree(self, context: ExecutionContext, worktree: Worktree, force: bool = False) -> None:
        args = ["git", "worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(worktree.path))
        result = self.runtime.execute(CommandSpec(args=args, cwd=worktree.repository, name="worktree.remove"), context).result
        if not result.success and worktree.path.exists():
            if force:
                shutil.rmtree(worktree.path, ignore_errors=True)
            else:
                raise RuntimeError(result.stderr or result.stdout)
        context.emit(Event(EventType.WORKTREE_DESTROYED, context.task.id, {"path": str(worktree.path)}))
        context.add_artifact(RuntimeLogArtifact(self.name, {"operation": "cleanup_worktree", "path": str(worktree.path)}))
        if context.worktree_path == worktree.path:
            context.worktree_path = None
            context.working_directory = None
            context.runtime_variables.pop("working_directory", None)
