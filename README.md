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

Phase 3 planning and workflow intelligence:

- Planner engine that transforms high-level engineering tasks into serializable execution plans
- Execution plans modeled as DAGs with dependency tracking, topological ordering, readiness checks, parallel groups, cycle detection, subtree extraction, and critical-path metrics
- Dynamic workflow construction from execution plans
- Reusable workflow nodes for planning, research, implementation, testing, verification, documentation, review, decisions, adaptive replanning, and human approval
- Conditional branching through composable branch rules
- Parallel execution of dependency-ready plan steps
- Dynamic skill selection based on capability match, tool availability, historical success metadata, cost, and execution time
- Adaptive subtree replanning that reuses completed steps and artifacts
- Planning metrics for planning time, workflow depth, width, parallelism, critical path, execution efficiency, and plan revisions

Phase 3.5 agent adapter layer:

- Provider-independent `AgentAdapter` interface for planning, coding, review, debugging, documentation, testing, refactoring, and architecture agents
- Structured `AgentResponse` objects with status, reasoning summary, artifacts, tool calls, metrics, warnings, and errors
- `AgentSession` tracking task, workflow, active step, provider, model, status, token usage, latency, cost, retries, and generated artifacts
- Agent registry adapter APIs: register, unregister, get, list, and capability resolution
- `MockAgentAdapter` for deterministic tests
- `CodexCLIAdapter` that invokes Codex CLI through the runtime layer and builds prompts from `ExecutionContext` and `ExecutionStep`
- Streaming chunks with `AgentStarted`, `AgentOutputChunk`, `AgentFinished`, and `AgentFailed` events
- Adapter failure recovery that can retry, switch to another compatible adapter, or escalate through the decision engine
- Dynamic planned execution now resolves execution steps through adapter capabilities before falling back to legacy skills

Phase 4 engineering workflow library:

- Declarative reusable workflow definitions with metadata, parameters, steps, dependencies, retry policies, verification stages, approval stages, and outputs
- Workflow registry APIs for registering, unregistering, listing, loading, validating, importing, and exporting workflows
- JSON and YAML workflow import/export support
- Built-in workflows:
  - `feature-development`
  - `bug-fix`
  - `refactoring`
  - `code-review`
  - `documentation`
  - `test-generation`
  - `dependency-upgrade`
- Workflow composition, for example feature development composes documentation and code review workflows
- Execution graph visualization artifacts containing DAG, timeline, state transitions, artifact graph, and workflow metrics
- Workflow metrics including duration, step timings, retries, critical path, parallel efficiency, success, and verification failures

The scheduler intentionally contains no engineering business logic. It selects a workflow and executes it through the workflow engine. Skills, agents, verification checks, repositories, and workflow definitions are replaceable.

For runtime execution that must isolate task work in Git worktrees, construct the scheduler with:

```python
from core.scheduler import Scheduler

scheduler = Scheduler.runtime_default("/path/to/repo")
```

`Scheduler.default()` remains available for in-memory orchestration and tests that do not touch a repository checkout.

For dynamic planning and execution:

```python
from core.scheduler import Scheduler
from core.task_manager import Task

scheduler = Scheduler.default()
task = Task(title="Build feature with tests", description="Implement and verify it", goal="Feature works")
result = scheduler.run_planned(task)
```

For a reusable engineering workflow:

```python
from core.scheduler import Scheduler

scheduler = Scheduler.default()
result = scheduler.run_workflow(
    workflow="feature-development",
    goal="Implement JWT Authentication",
    parameters={"priority": "high", "max_retries": 3, "verification": "full"},
)
```

## Setup

The project uses `uv` as the only supported Python package and environment manager.

```bash
git clone <repo>
cd loop-engineering

uv venv
source .venv/bin/activate

uv sync

uv run loop --help
```

## Common Commands

```bash
uv run pytest
uv run coverage run -m pytest
uv run coverage report
uv run ruff check .
uv run mypy .
uv run loop doctor
uv run loop workflows
uv run loop benchmark
uv run loop run feature-development --goal "Implement JWT Authentication"
```

Current measured coverage for `core,agents,skills,verification,runtime,tools,worktree,loop_cli` is 91%.

## CLI

After `uv sync`, run the CLI with `uv run loop`.

Examples:

```bash
uv run loop --help
uv run loop version
uv run loop workflows
uv run loop adapters
uv run loop doctor
uv run loop config init
uv run loop run feature-development --goal "Implement JWT Authentication"
uv run loop run bug-fix --issue "Parser crashes on empty input" --parameters '{"max_retries": 3}'
uv run loop new-project --goal "Build a FastAPI Todo backend"
uv run loop benchmark all --json
```

Validation from a clean checkout:

```bash
uv venv
source .venv/bin/activate

uv sync

uv run loop doctor
uv run loop workflows
uv run loop benchmark
```

`uv sync` installs the project in editable mode and exposes the `loop` entry point through `uv run`.

Useful command equivalents:

```bash
uv run pytest
uv run coverage run -m pytest
uv run coverage report
uv run loop benchmark
uv run loop doctor
uv run loop run feature-development --goal "Implement JWT Authentication"
```

Common run options:

- `--repo` executes with runtime worktree support for a Git repository.
- `--parameters` accepts a JSON object, `@file.json`, or comma-separated `key=value` pairs.
- `--adapter codex --model <name>` routes execution through the Codex CLI adapter.
- `--dry-run` prints the generated execution plan without running it.
- `--json`, `--quiet`, and `--verbose` control output format.

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
