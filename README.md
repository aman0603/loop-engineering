# Loop Engineering

Loop Engineering is an orchestration framework for autonomous software engineering tasks. It is organized around tasks, skills, workflows, verification, and feedback-driven retries.

This repository currently implements Phase 1:

- Task model and state lifecycle
- Execution context carrying task, configuration, metadata, event bus, artifacts, metrics, cancellation, runtime variables, and observability data
- Structured artifact store with plan, implementation, verification, log, patch, review, and documentation artifact types
- Event-driven execution lifecycle
- Declarative workflow state machine
- Decision engine for retry, completion, and abort decisions
- Registries for agents, skills, workflows, verifiers, and tools
- Scheduler with priority queue and dependency checks
- Planner and coding skills behind context-first common interfaces
- Agent wrappers that coordinate skills through structured results
- Workflow graph engine
- Verification pipeline
- Feedback engine
- Retry loop that replans instead of blindly rerunning
- In-memory and JSON task repositories

Phase 2 runtime execution layer:

- Tool runtime abstraction with shell, filesystem, Git, Python, test, search placeholder, and HTTP placeholder tools
- Local runtime and command runner with stdout/stderr capture, exit codes, duration, retries, timeout, async execution, streaming callback support, and cancellation
- Git worktree manager for isolated per-task worktrees, branch checkout, dirty-state detection, commit, rollback, and cleanup
- Structured file operations for read, write, patch, delete, list, and search
- Runtime verification checks for configurable commands such as pytest, lint, formatting, and type checking
- Runtime artifacts for commands, tests, diffs, builds, patches, and runtime logs
- Runtime events for commands, runtimes, worktrees, verification execution, tests, and recovery decisions

The scheduler intentionally contains no engineering business logic. It selects a workflow and executes it through the workflow engine. Skills, agents, verification checks, repositories, and workflow definitions are replaceable.

For runtime execution that must isolate task work in Git worktrees, construct the scheduler with:

```python
from core.scheduler import Scheduler

scheduler = Scheduler.runtime_default("/path/to/repo")
```

`Scheduler.default()` remains available for in-memory orchestration and tests that do not touch a repository checkout.

## Run Tests

```bash
python -m pytest
```

With development dependencies installed:

```bash
python -m coverage run -m pytest
python -m coverage report
```

Current measured coverage for `core,agents,skills,verification,runtime,tools,worktree` is 91%.

## Minimal Usage

```python
from core.scheduler import Scheduler
from core.task_manager import Task

scheduler = Scheduler.default()
task = Task(
    title="Add health check",
    description="Expose a health endpoint.",
    goal="A service health endpoint exists.",
    acceptance_criteria=["Health endpoint returns a success payload"],
)

scheduler.submit(task)
result = scheduler.run_next()
assert result.status.value == "DONE"
```

## Phase Roadmap

Phase 2 will add worktree management, memory providers, an event bus adapter layer, and plugin loading. Phase 3 will expand agents, human approval nodes, API/dashboard surfaces, and richer workflow graphs. Phase 4 will focus on parallel workflows, metrics, distributed execution, and advanced scheduling.
