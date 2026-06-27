from pathlib import Path

from core import Decision, DecisionEngine, ExecutionConfig, ExecutionContext
from core.events import EventType
from core.task_manager import InMemoryTaskRepository, Task, TaskStatus, VerificationOutcome
from core.scheduler import Scheduler, WorkflowRegistry
from core.workflow import FunctionNode, NodeResult, WorkflowDefinition
from runtime import CommandRunner, CommandSpec, CommandStatus, LocalRuntime
from tools import (
    DeleteFileRequest,
    FileSystemTool,
    GitTool,
    HTTPTool,
    PatchFileRequest,
    PythonTool,
    SearchTool,
    ShellTool,
    TestTool,
    WriteFileRequest,
)
from verification import CommandVerificationCheck, RuntimeVerificationPipeline
from worktree import WorktreeManager


def test_command_runner_captures_success_and_artifacts(tmp_path):
    context = ExecutionContext(task=Task(title="cmd", description="run", goal="ok"), working_directory=tmp_path)
    result = CommandRunner().run(CommandSpec(args=["python3", "-c", "print('ok')"], cwd=tmp_path), context)

    assert result.success
    assert result.stdout.strip() == "ok"
    assert result.exit_code == 0
    assert context.artifact_store.latest("command") is not None
    assert {event.type for event in context.event_bus.list()} >= {
        EventType.COMMAND_STARTED,
        EventType.COMMAND_FINISHED,
    }


def test_runtime_timeout_returns_structured_result(tmp_path):
    context = ExecutionContext(task=Task(title="timeout", description="run", goal="timeout"), working_directory=tmp_path)
    result = LocalRuntime().execute(
        CommandSpec(args=["python3", "-c", "import time; time.sleep(1)"], cwd=tmp_path, timeout_seconds=0.01),
        context,
    ).result

    assert result.status == CommandStatus.TIMED_OUT
    assert not result.success
    assert context.artifact_store.latest("runtime_log") is not None


def test_async_command_can_be_cancelled(tmp_path):
    context = ExecutionContext(task=Task(title="cancel", description="run", goal="cancel"), working_directory=tmp_path)
    handle = CommandRunner().run_async(
        CommandSpec(args=["python3", "-c", "import time; time.sleep(2)"], cwd=tmp_path, timeout_seconds=5),
        context,
    )

    context.cancellation_token.cancel("test cancellation")
    result = handle.result(timeout=3)

    assert result.status in {CommandStatus.CANCELLED, CommandStatus.TIMED_OUT}
    assert not result.success


def test_filesystem_tool_structured_operations(tmp_path):
    context = ExecutionContext(task=Task(title="fs", description="files", goal="files"), working_directory=tmp_path)
    tool = FileSystemTool()

    assert tool.write_file(context, WriteFileRequest("src/app.py", "print('hello')")).success
    read = tool.read_file(context, "src/app.py")
    patch = tool.patch_file(context, PatchFileRequest("src/app.py", "hello", "hi"))
    listing = tool.list_directory(context, "src")
    search = tool.search_files(context, "hi", "src")
    delete = tool.delete_file(context, DeleteFileRequest("src/app.py"))

    assert read.output["content"] == "print('hello')"
    assert patch.success
    assert listing.output["entries"] == ["app.py"]
    assert len(search.output["matches"]) == 1
    assert delete.success
    assert not (tmp_path / "src" / "app.py").exists()


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = CommandRunner()
    context = ExecutionContext(task=Task(title="repo", description="init", goal="repo"), working_directory=repo)
    for args in [
        ["git", "init", "-b", "main"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test User"],
    ]:
        result = runner.run(CommandSpec(args=args, cwd=repo), context)
        assert result.success, result.stderr
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    assert runner.run(CommandSpec(args=["git", "add", "README.md"], cwd=repo), context).success
    assert runner.run(CommandSpec(args=["git", "commit", "-m", "init"], cwd=repo), context).success
    return repo


def test_worktree_lifecycle_dirty_commit_rollback_cleanup(tmp_path):
    repo = init_repo(tmp_path)
    context = ExecutionContext(task=Task(title="worktree", description="isolate", goal="isolate"))
    manager = WorktreeManager(repo, root=tmp_path / "worktrees")

    worktree = manager.create_worktree(context, branch="loop/test")
    assert worktree.path.exists()
    assert context.working_directory == worktree.path
    assert (repo / "README.md").read_text(encoding="utf-8") == "base\n"

    (worktree.path / "feature.txt").write_text("feature\n", encoding="utf-8")
    assert manager.is_dirty(context, worktree)
    manager.rollback_changes(context, worktree)
    assert not manager.is_dirty(context, worktree)

    (worktree.path / "feature.txt").write_text("feature\n", encoding="utf-8")
    sha = manager.commit_changes(context, worktree, "feature")
    assert sha
    assert not manager.is_dirty(context, worktree)

    manager.cleanup_worktree(context, worktree, force=True)
    assert not worktree.path.exists()
    assert {event.type for event in context.event_bus.list()} >= {
        EventType.WORKTREE_CREATED,
        EventType.WORKTREE_DESTROYED,
    }


def test_scheduler_executes_configured_workflow_inside_worktree(tmp_path):
    repo = init_repo(tmp_path)
    registry = WorkflowRegistry()

    def write_in_worktree(ctx):
        assert ctx.working_directory == ctx.worktree_path
        assert ctx.worktree_path is not None
        (ctx.worktree_path / "isolated.txt").write_text("isolated\n", encoding="utf-8")
        ctx.task.transition_to(TaskStatus.PLANNING)
        ctx.task.transition_to(TaskStatus.EXECUTING)
        ctx.task.transition_to(TaskStatus.VERIFYING)
        ctx.task.transition_to(TaskStatus.DONE)
        return NodeResult(context=ctx, completed=True)

    registry.register(
        WorkflowDefinition(
            name="worktree_workflow",
            start_node="write",
            nodes={"write": FunctionNode("write", write_in_worktree)},
        )
    )
    scheduler = Scheduler(
        repository=InMemoryTaskRepository(),
        workflow_registry=registry,
        worktree_manager=WorktreeManager(repo, root=tmp_path / "scheduler-worktrees"),
    )
    task = Task(title="isolated", description="write", goal="isolated", metadata={"workflow": "worktree_workflow"})

    scheduler.submit(task)
    result = scheduler.run_next()

    assert result is not None
    assert result.status.value == "DONE"
    assert not (repo / "isolated.txt").exists()
    assert EventType.WORKTREE_CREATED in {event.type for event in scheduler.event_bus.list()}
    assert EventType.WORKTREE_DESTROYED in {event.type for event in scheduler.event_bus.list()}


def test_runtime_default_scheduler_configures_worktree_manager(tmp_path):
    repo = init_repo(tmp_path)
    scheduler = Scheduler.runtime_default(repo, worktree_root=tmp_path / "runtime-default-worktrees")

    assert scheduler.worktree_manager is not None


def test_shell_tool_and_scheduler_tool_registry(tmp_path):
    from core.scheduler import Scheduler

    scheduler = Scheduler.default()
    context = ExecutionContext(task=Task(title="tool", description="run", goal="run"), working_directory=tmp_path)
    shell = scheduler.tool_registry.get("shell")

    result = shell.run(context, ["python3", "-c", "print('tool')"])

    assert isinstance(shell, ShellTool)
    assert result.success
    assert "tool" in result.output["command"]["stdout"]
    assert set(scheduler.tool_registry.names()) >= {"shell", "filesystem", "git", "python", "test", "search", "http"}


def test_python_test_git_and_placeholder_tools(tmp_path):
    repo = init_repo(tmp_path)
    context = ExecutionContext(task=Task(title="tools", description="tools", goal="tools"), working_directory=repo)
    (repo / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    python_result = PythonTool().run(context, "print('pytool')")
    test_result = TestTool().run(context, ["python3", "-m", "pytest", "-q"])
    git_status = GitTool().run(context, ["status", "--short"])
    git_diff = GitTool().run(context, ["diff"])
    search_result = SearchTool().run(context, {"q": "placeholder"})
    http_result = HTTPTool().run(context, {"url": "https://example.invalid"})

    assert python_result.success
    assert "pytool" in python_result.output["command"]["stdout"]
    assert test_result.success
    assert git_status.success
    assert git_diff.success
    assert context.artifact_store.latest("test") is not None
    assert not search_result.success
    assert not http_result.success


def test_runtime_verification_pipeline_runs_configured_commands(tmp_path):
    (tmp_path / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    context = ExecutionContext(
        task=Task(title="verify", description="tests", goal="tests"),
        configuration=ExecutionConfig(verification_commands={"pytest": ["python3", "-m", "pytest", "-q"]}),
        working_directory=tmp_path,
    )

    report = RuntimeVerificationPipeline.from_context(context).run(context)

    assert report.passed
    assert report.results[0].outcome == VerificationOutcome.PASSED
    assert context.artifact_store.latest("test") is not None
    assert {event.type for event in context.event_bus.list()} >= {
        EventType.VERIFICATION_EXECUTED,
        EventType.TESTS_PASSED,
    }


def test_command_verification_failure_produces_failure_result(tmp_path):
    context = ExecutionContext(task=Task(title="verify", description="fail", goal="fail"), working_directory=tmp_path)
    check = CommandVerificationCheck("lint", ["python3", "-c", "import sys; sys.exit(2)"])

    result = check.run(context)

    assert result.outcome == VerificationOutcome.FAILED
    assert context.artifact_store.latest("build") is not None
    assert EventType.TESTS_FAILED in {event.type for event in context.event_bus.list()}


def test_recovery_decision_engine_runtime_failure_paths():
    context = ExecutionContext(
        task=Task(title="recover", description="recover", goal="recover"),
        configuration=ExecutionConfig(command_retries=1),
    )
    engine = DecisionEngine()

    assert engine.decide_recovery(context, {"kind": "command", "attempts": 1}).decision == Decision.RETRY_COMMAND
    assert engine.decide_recovery(context, {"kind": "worktree"}).decision == Decision.ROLLBACK_WORKTREE
    assert engine.decide_recovery(context, {"kind": "runtime"}).decision == Decision.RECREATE_RUNTIME
    assert engine.decide_recovery(context, {"optional": True}).decision == Decision.SKIP_OPTIONAL_STEP
    assert engine.decide_recovery(context, {"kind": "unknown"}).decision == Decision.ABORT
