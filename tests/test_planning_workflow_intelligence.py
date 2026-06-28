from core import ExecutionContext
from core.events import EventType
from core.planning import ExecutionPlan, ExecutionStep, PlannerEngine, RetryPolicy
from core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from core.scheduler import Scheduler
from core.task_manager import Task
from core.workflow import (
    BranchRule,
    DecisionNode,
    DynamicWorkflowBuilder,
    HumanApprovalNode,
    NodeResult,
    PlanStepNode,
    PlanWorkflowExecutor,
    WorkflowEngine,
    WorkflowStatus,
)
from skills import Skill, SkillResult
from tools import SearchTool, ShellTool


class CapabilitySkill(Skill):
    def __init__(self, name, capabilities, tools=None, success=True):
        self.name = name
        self.metadata = {
            "capabilities": capabilities,
            "tools": tools or [],
            "cost": 1,
            "avg_duration_ms": 100,
        }
        self.success = success

    def run(self, context):
        artifact_type = {
            "planning": "plan",
            "coding": "implementation",
            "testing": "test",
            "documentation": "documentation",
            "research": "documentation",
            "review": "review",
        }.get(self.metadata["capabilities"][0], "log")
        return SkillResult(
            success=self.success,
            output={artifact_type: {"skill": self.name}},
            logs=[f"{self.name} ran"],
        )


def registries():
    skills = SkillRegistry()
    for skill in [
        CapabilitySkill("skill.planning", ["planning"]),
        CapabilitySkill("skill.coding", ["coding"]),
        CapabilitySkill("skill.testing", ["testing"], ["shell"]),
        CapabilitySkill("skill.documentation", ["documentation"]),
        CapabilitySkill("skill.research", ["research"], ["search"]),
    ]:
        skills.register(skill)
    tools = ToolRegistry()
    tools.register(ShellTool())
    tools.register(SearchTool())
    agents = AgentRegistry()
    return skills, tools, agents


def test_planner_engine_generates_serializable_execution_plan_with_metrics():
    skills, tools, agents = registries()
    task = Task(
        title="Research build test docs",
        description="Research then build feature with tests and documentation",
        goal="Feature shipped",
        acceptance_criteria=["feature works"],
    )
    context = ExecutionContext(task=task)

    plan = PlannerEngine().plan(task, context, skills, tools, agents)
    roundtrip = ExecutionPlan.from_dict(plan.to_dict())

    assert [step.required_capability for step in plan.steps] == [
        "planning",
        "research",
        "coding",
        "testing",
        "documentation",
    ]
    assert roundtrip.to_dict() == plan.to_dict()
    assert context.artifact_store.latest("plan") is not None
    assert context.metrics.values["planning.workflow_depth"] == 5
    assert EventType.PLANNING_COMPLETED in {event.type for event in context.event_bus.list()}


def test_execution_plan_dag_dependency_resolution_parallel_groups_and_critical_path():
    a = ExecutionStep(id="a", description="a")
    b = ExecutionStep(id="b", description="b", dependencies=["a"])
    c = ExecutionStep(id="c", description="c", dependencies=["a"])
    d = ExecutionStep(id="d", description="d", dependencies=["b", "c"])
    plan = ExecutionPlan(task_id="task", steps=[d, c, a, b])

    assert [step.id for step in plan.topological_order()] == ["a", "b", "c", "d"]
    assert [step.id for step in plan.ready_steps(set())] == ["a"]
    assert sorted(step.id for step in plan.ready_steps({"a"})) == ["b", "c"]
    assert [[step.id for step in group] for group in plan.parallel_groups()] == [["a"], ["b", "c"], ["d"]]
    assert plan.metrics()["workflow_width"] == 2
    assert plan.critical_path() in [["a", "b", "d"], ["a", "c", "d"]]


def test_execution_plan_cycle_detection():
    a = ExecutionStep(id="a", description="a", dependencies=["b"])
    b = ExecutionStep(id="b", description="b", dependencies=["a"])

    try:
        ExecutionPlan(task_id="task", steps=[a, b])
    except ValueError as exc:
        assert "cycle" in str(exc)
    else:
        raise AssertionError("cycle should fail")


def test_plan_workflow_executor_runs_parallel_ready_steps():
    skills, _, _ = registries()
    context = ExecutionContext(task=Task(title="parallel", description="parallel", goal="parallel"))
    plan = ExecutionPlan(
        task_id=context.task.id,
        steps=[
            ExecutionStep(id="a", description="a", expected_artifacts=["a"]),
            ExecutionStep(id="b", description="b", expected_artifacts=["b"]),
            ExecutionStep(id="c", description="c", dependencies=["a", "b"], expected_artifacts=["c"]),
        ],
    )

    result = PlanWorkflowExecutor(skills=skills).execute(plan, context)

    assert result.success
    assert result.completed_steps == {"a", "b", "c"}
    assert context.metrics.values["planning.execution_efficiency"] == 1
    assert [event.type for event in context.event_bus.list()].count(EventType.PARALLEL_GROUP_STARTED) == 2


def test_conditional_branching_decision_node_selects_runtime_target():
    context = ExecutionContext(task=Task(title="branch", description="branch", goal="branch"))
    context.runtime_variables["tests_failed"] = True
    node = DecisionNode(
        rules=[BranchRule("debug-on-test-failure", lambda ctx: ctx.runtime_variables["tests_failed"], "debug")],
        default_target="continue",
    )

    result = node.run(context)

    assert result.next_node == "debug"
    assert context.event_bus.list()[-1].type == EventType.BRANCH_SELECTED


def test_adaptive_replanning_replans_only_failed_subtree_and_reuses_completed_steps():
    skills, _, _ = registries()
    context = ExecutionContext(task=Task(title="replan", description="replan", goal="replan"))
    plan = ExecutionPlan(
        task_id=context.task.id,
        steps=[
            ExecutionStep(id="setup", description="setup"),
            ExecutionStep(
                id="fail",
                description="fail",
                dependencies=["setup"],
                retry_policy=RetryPolicy(max_attempts=2),
            ),
            ExecutionStep(id="after", description="after", dependencies=["fail"]),
        ],
    )
    attempts = {"fail": 0}

    def handler(ctx, step):
        if step.id == "fail":
            attempts["fail"] += 1
            return attempts["fail"] > 1
        return True

    result = PlanWorkflowExecutor(skills=skills, step_handlers={"fail": handler}).execute(plan, context)

    assert result.success
    assert result.replanned
    assert "setup" in context.runtime_variables["completed_plan_steps"]
    assert context.runtime_variables["execution_plan"].metadata["subtree_root"] == "fail"
    assert EventType.PLAN_REVISED in {event.type for event in context.event_bus.list()}


def test_plan_step_node_executes_skill_and_produces_expected_artifact():
    skills, _, _ = registries()
    context = ExecutionContext(task=Task(title="node", description="node", goal="node"))
    step = ExecutionStep(
        id="code",
        description="implement",
        required_skill="skill.coding",
        expected_artifacts=["implementation"],
    )

    result = PlanStepNode(step, skills).run(context)

    assert not result.failed
    assert step.status.value == "COMPLETED"
    assert context.artifact_store.latest("implementation") is not None
    assert EventType.PLAN_STEP_FINISHED in {event.type for event in context.event_bus.list()}


def test_dynamic_workflow_builder_executes_plan_through_workflow_engine():
    skills, _, _ = registries()
    context = ExecutionContext(task=Task(title="dynamic", description="dynamic", goal="dynamic"))
    plan = ExecutionPlan(task_id=context.task.id, steps=[ExecutionStep(id="only", description="only")])
    workflow = DynamicWorkflowBuilder(PlanWorkflowExecutor(skills=skills)).build(plan)

    execution = WorkflowEngine().run(workflow, context)

    assert execution.status == WorkflowStatus.COMPLETED
    assert execution.visited_nodes == ["execute_plan"]
    assert context.end_time is not None


def test_human_approval_node_pauses_until_runtime_variable_is_set():
    context = ExecutionContext(task=Task(title="approval", description="approval", goal="approval"))
    node = HumanApprovalNode("approved")

    paused = node.run(context)
    context.runtime_variables["approved"] = True
    resumed = node.run(context)

    assert paused.pause_requested
    assert not resumed.pause_requested


def test_scheduler_generates_and_executes_dynamic_plan():
    scheduler = Scheduler.default()
    task = Task(
        title="Build feature with tests",
        description="Build and test a feature",
        goal="Feature works",
        acceptance_criteria=["feature works"],
        max_attempts=2,
    )

    result = scheduler.run_planned(task)

    assert result.status.value == "DONE"
    assert result.metadata["last_plan"]["steps"]
    assert result.metadata["last_execution"]["metrics"]["values"]["planning.execution_efficiency"] == 1
    assert EventType.TASK_COMPLETED in {event.type for event in scheduler.event_bus.list()}
