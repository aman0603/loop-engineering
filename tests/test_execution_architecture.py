from core import (
    AgentRegistry,
    ArtifactType,
    Decision,
    DecisionEngine,
    ExecutionContext,
    ToolRegistry,
    VerifierRegistry,
)
from core.artifacts import PlanArtifact
from core.events import Event, EventType, InMemoryEventBus
from core.registries import WorkflowRegistry
from core.scheduler import Scheduler
from core.state_machine import StateMachine, WorkflowState
from core.task_manager import InMemoryTaskRepository, Task, TaskStatus, VerificationOutcome, VerificationResult, utc_now
from core.workflow import FunctionNode, NodeResult, WorkflowDefinition, WorkflowEngine, WorkflowStatus
from agents.planner import PlannerAgent
from verification import VerificationPipeline


def test_execution_context_tracks_lifecycle_artifacts_events_and_metrics():
    event_bus = InMemoryEventBus()
    task = Task(title="Plan", description="Plan work", goal="Have a plan")
    context = ExecutionContext(task=task, event_bus=event_bus)

    context.add_artifact(PlanArtifact("planner", {"steps": ["inspect"]}))
    context.emit(Event(EventType.TASK_STARTED, task.id, {"source": "test"}))
    context.log("test", "created execution context")
    context.metrics.increment("custom")
    context.finish()

    snapshot = context.observability_snapshot()

    assert snapshot["task_id"] == task.id
    assert snapshot["end_time"] is not None
    assert snapshot["metrics"]["counters"]["custom"] == 1
    assert snapshot["metrics"]["counters"]["artifacts_produced"] == 2
    assert snapshot["artifacts"][0]["type"] == ArtifactType.PLAN.value
    assert snapshot["events"] == [EventType.TASK_STARTED.value]
    assert task.execution_logs[0].message == "created execution context"


def test_state_machine_enforces_declarative_transitions():
    context = ExecutionContext(task=Task(title="Feature", description="Build", goal="Done"))
    machine = StateMachine()

    machine.transition_for_event(context, "plan")
    machine.transition_for_event(context, "implement")
    machine.transition_for_event(context, "verify")
    machine.transition_for_event(context, "complete")

    assert context.workflow_state == WorkflowState.DONE.value
    assert context.task.status == TaskStatus.DONE
    assert [item["to"] for item in context.state_transitions] == [
        WorkflowState.PLANNING.value,
        WorkflowState.IMPLEMENTING.value,
        WorkflowState.VERIFYING.value,
        WorkflowState.DONE.value,
    ]


def test_state_machine_rejects_invalid_transition():
    context = ExecutionContext(task=Task(title="Feature", description="Build", goal="Done"))
    machine = StateMachine()

    try:
        machine.transition(context, WorkflowState.DONE)
    except ValueError as exc:
        assert "invalid workflow transition" in str(exc)
    else:
        raise AssertionError("invalid transition should fail")


def test_decision_engine_completes_retries_and_aborts():
    engine = DecisionEngine()
    task = Task(title="Feature", description="Build", goal="Done", max_attempts=2)
    context = ExecutionContext(task=task)
    passed = VerificationResult(
        name="unit",
        outcome=VerificationOutcome.PASSED,
        summary="ok",
        started_at=utc_now(),
        finished_at=utc_now(),
    )
    failed = VerificationResult(
        name="unit",
        outcome=VerificationOutcome.FAILED,
        summary="bad",
        started_at=utc_now(),
        finished_at=utc_now(),
    )

    assert engine.decide(context, verification=type("Report", (), {"passed": True, "metrics": {}, "failed_results": []})()).decision == Decision.COMPLETE

    context.retry_count = 1
    retry_report = type("Report", (), {"passed": False, "metrics": {}, "failed_results": [failed]})()
    assert engine.decide(context, retry_report).decision == Decision.RETRY

    context.retry_count = 2
    assert engine.decide(context, retry_report).decision == Decision.ABORT
    assert passed.passed


def test_registry_resolution_for_new_core_registries():
    agent_registry = AgentRegistry()
    verifier_registry = VerifierRegistry()
    workflow_registry = WorkflowRegistry()
    tool_registry = ToolRegistry()
    agent = PlannerAgent()
    verifier = VerificationPipeline().checks[0]
    workflow = WorkflowDefinition("example", "start", {})

    class Tool:
        name = "terminal"

    agent_registry.register(agent)
    verifier_registry.register(verifier)
    workflow_registry.register(workflow)
    tool_registry.register(Tool())

    assert agent_registry.get("planner") is agent
    assert verifier_registry.get(verifier.name) is verifier
    assert workflow_registry.get("example") is workflow
    assert tool_registry.get("terminal").name == "terminal"


def test_workflow_engine_emits_events_and_finishes_context():
    task = Task(title="Tiny", description="Run", goal="Complete")
    context = ExecutionContext(task=task)

    def complete_node(ctx):
        ctx.add_artifact(PlanArtifact("node", {"steps": []}))
        return NodeResult(context=ctx, completed=True)

    definition = WorkflowDefinition(
        name="tiny",
        start_node="complete",
        nodes={"complete": FunctionNode("complete", complete_node)},
    )

    execution = WorkflowEngine().run(definition, context)

    assert execution.status == WorkflowStatus.COMPLETED
    assert context.end_time is not None
    assert [event.type for event in context.event_bus.list()] == [
        EventType.WORKFLOW_STARTED,
        EventType.WORKFLOW_FINISHED,
    ]


def test_scheduler_dispatch_exposes_observability_and_new_events():
    scheduler = Scheduler.default()
    task = Task(title="Docs", description="Document setup", goal="Docs", acceptance_criteria=["setup covered"])

    scheduler.submit(task)
    result = scheduler.run_next()

    assert result is not None
    assert result.status == TaskStatus.DONE
    assert scheduler.workflow_registry.get("default_engineering").name == "default_engineering"
    assert scheduler.agent_registry.get("planner").name == "planner"
    assert scheduler.skill_registry.get("planning.default").name == "planning.default"
    assert scheduler.verifier_registry.names()
    assert set(scheduler.tool_registry.names()) >= {"shell", "filesystem", "git", "python", "test", "search", "http"}
    assert result.metadata["last_execution"]["retries"] == 1
    assert {event.type for event in scheduler.event_bus.list()} >= {
        EventType.TASK_SCHEDULED,
        EventType.WORKFLOW_STARTED,
        EventType.PLANNING_STARTED,
        EventType.SKILL_STARTED,
        EventType.VERIFICATION_STARTED,
        EventType.DECISION_MADE,
        EventType.WORKFLOW_FINISHED,
    }


def test_scheduler_uses_registered_custom_workflow():
    registry = WorkflowRegistry()

    def complete_node(ctx):
        ctx.task.transition_to(TaskStatus.PLANNING)
        ctx.task.transition_to(TaskStatus.EXECUTING)
        ctx.task.transition_to(TaskStatus.VERIFYING)
        ctx.task.transition_to(TaskStatus.DONE)
        return NodeResult(context=ctx, completed=True)

    registry.register(
        WorkflowDefinition(
            name="custom",
            start_node="complete",
            nodes={"complete": FunctionNode("complete", complete_node)},
        )
    )
    scheduler = Scheduler(repository=InMemoryTaskRepository(), workflow_registry=registry)
    task = Task(title="Custom", description="Run custom", goal="Done", metadata={"workflow": "custom"})

    scheduler.submit(task)
    result = scheduler.run_next()

    assert result is not None
    assert result.status == TaskStatus.DONE
    assert result.metadata["last_execution"]["events"] == [
        EventType.TASK_CREATED.value,
        EventType.TASK_SCHEDULED.value,
        EventType.TASK_STARTED.value,
        EventType.WORKFLOW_STARTED.value,
        EventType.WORKFLOW_FINISHED.value,
    ]
