from agents.adapters import AgentResponseStatus, CodexCLIAdapter, MockAgentAdapter
from core import Decision, ExecutionContext
from core.decision import DecisionEngine
from core.events import EventType
from core.planning import ExecutionPlan, ExecutionStep, RetryPolicy
from core.registries import AgentRegistry, SkillRegistry
from core.task_manager import Task
from core.workflow import PlanWorkflowExecutor
from runtime import CommandResult, CommandSpec, CommandStatus, RuntimeResult


def test_agent_registry_adapter_registration_and_capability_resolution():
    registry = AgentRegistry()
    coding = MockAgentAdapter(name="mock.coding", capabilities=["coding"])
    docs = MockAgentAdapter(name="mock.docs", capabilities=["documentation"])

    registry.register_adapter(coding)
    registry.register_adapter(docs)

    assert registry.get_adapter("mock.coding") is coding
    assert registry.find_adapter_for_capability("documentation") is docs
    assert registry.adapter_names() == ["mock.coding", "mock.docs"]

    registry.unregister_adapter("mock.coding")

    assert registry.find_adapter_for_capability("coding") is None


def test_mock_adapter_session_lifecycle_and_structured_response():
    context = ExecutionContext(task=Task(title="adapter", description="adapter", goal="adapter"))
    step = ExecutionStep(id="code", description="code", required_capability="coding", expected_artifacts=["implementation"])
    adapter = MockAgentAdapter(capabilities=["coding"])

    response = adapter.execute(step, context)

    assert response.status == AgentResponseStatus.SUCCEEDED
    assert response.reasoning_summary
    assert response.session_id in context.agent_sessions
    assert context.agent_sessions[response.session_id].status.value == "COMPLETED"
    assert context.agent_sessions[response.session_id].artifacts_generated
    assert context.artifact_store.latest("implementation") is not None


def test_adapter_streaming_emits_output_chunk_events():
    context = ExecutionContext(task=Task(title="stream", description="stream", goal="stream"))
    step = ExecutionStep(id="docs", description="docs", required_capability="documentation")
    adapter = MockAgentAdapter(capabilities=["documentation"])

    chunks = list(adapter.stream(step, context))

    assert [chunk.content for chunk in chunks] == ["mock ", "adapter ", "output"]
    assert EventType.AGENT_OUTPUT_CHUNK in {event.type for event in context.event_bus.list()}
    assert context.agent_sessions[chunks[0].session_id].status.value == "COMPLETED"


def test_plan_executor_switches_adapter_on_failure():
    context = ExecutionContext(task=Task(title="switch", description="switch", goal="switch"))
    agents = AgentRegistry()
    agents.register_adapter(MockAgentAdapter(name="mock.primary", capabilities=["coding"], fail_for_steps={"code"}))
    agents.register_adapter(MockAgentAdapter(name="mock.backup", capabilities=["coding"]))
    plan = ExecutionPlan(
        task_id=context.task.id,
        steps=[
            ExecutionStep(
                id="code",
                description="code",
                required_capability="coding",
                retry_policy=RetryPolicy(max_attempts=2),
                expected_artifacts=["implementation"],
            )
        ],
    )

    result = PlanWorkflowExecutor(skills=SkillRegistry(), agents=agents).execute(plan, context)

    assert result.success
    assert plan.step_map["code"].metadata["adapter"] == "mock.backup"
    assert EventType.AGENT_FAILED in {event.type for event in context.event_bus.list()}
    assert EventType.DECISION_MADE in {event.type for event in context.event_bus.list()}


class FakeRuntime:
    name = "fake.runtime"

    def __init__(self, success=True):
        self.success = success
        self.last_spec = None

    def execute(self, spec: CommandSpec, context: ExecutionContext) -> RuntimeResult:
        self.last_spec = spec
        status = CommandStatus.SUCCEEDED if self.success else CommandStatus.FAILED
        return RuntimeResult(
            CommandResult(
                command_id="cmd_fake",
                args=spec.args,
                cwd=str(spec.cwd) if spec.cwd else None,
                stdout="codex output",
                stderr="" if self.success else "codex failed",
                exit_code=0 if self.success else 1,
                duration_ms=1,
                status=status,
            )
        )


def test_codex_cli_adapter_uses_runtime_and_returns_structured_artifact():
    runtime = FakeRuntime()
    context = ExecutionContext(task=Task(title="codex", description="run codex", goal="done"))
    step = ExecutionStep(id="code", description="code", required_capability="coding", expected_artifacts=["implementation"])
    adapter = CodexCLIAdapter(runtime=runtime, executable="codex-test")

    response = adapter.execute(step, context)

    assert response.success
    assert response.reasoning_summary == "codex output"
    assert runtime.last_spec.args[0] == "codex-test"
    assert runtime.last_spec.args[1] == "exec"
    assert '"step"' in runtime.last_spec.args[2]
    assert context.artifact_store.latest("runtime_log") is not None


def test_codex_cli_adapter_failure_and_streaming_events():
    runtime = FakeRuntime(success=False)
    context = ExecutionContext(task=Task(title="codex", description="run codex", goal="done"))
    step = ExecutionStep(id="code", description="code", required_capability="coding")
    adapter = CodexCLIAdapter(runtime=runtime, executable="codex-test")

    response = adapter.execute(step, context)
    chunks = list(adapter.stream(step, context))

    assert not response.success
    assert response.errors == ["codex failed"]
    assert chunks
    assert EventType.AGENT_FAILED in {event.type for event in context.event_bus.list()}


def test_decision_engine_escalates_when_no_adapter_recovery_exists():
    context = ExecutionContext(task=Task(title="fail", description="fail", goal="fail"))

    decision = DecisionEngine().decide_recovery(
        context,
        {"kind": "agent_adapter", "attempts": 1, "max_attempts": 1, "replacement_available": False},
    )

    assert decision.decision == Decision.ESCALATE

