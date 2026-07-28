import pytest

from agents.adapters import AgentCapability, AgentHealth, AgentResponse, AgentResponseStatus, MockAgentAdapter
from core.events import EventType
from core.planning import RetryPolicy
from core.scheduler import Scheduler
from core.task_manager import TaskStatus
from core.workflow import EngineeringWorkflowDefinition, WorkflowStepSpec


BUILT_INS = [
    "feature-development",
    "bug-fix",
    "refactoring",
    "code-review",
    "documentation",
    "test-generation",
    "dependency-upgrade",
]


@pytest.mark.parametrize("workflow_name", BUILT_INS)
def test_builtin_workflows_execute_through_library(workflow_name):
    scheduler = Scheduler.default()

    result = scheduler.run_workflow(
        workflow=workflow_name,
        goal=f"Complete {workflow_name}",
        parameters={"max_retries": 2, "verification": "full", "human_review": "required"},
    )

    assert result.status == TaskStatus.DONE
    assert result.metadata["last_plan"]["metadata"]["workflow"] == workflow_name
    assert result.metadata["last_plan"]["steps"]
    assert result.metadata["workflow_visualization"]["type"] == "workflow_visualization"
    assert result.metadata["last_execution"]["metrics"]["values"][f"workflow.{workflow_name}.success"] == 1
    assert EventType.TASK_COMPLETED in {event.type for event in scheduler.event_bus.list()}


def test_workflow_registry_discovers_validates_and_unregisters_workflows():
    scheduler = Scheduler.default()

    names = sorted(workflow.name for workflow in scheduler.workflow_registry.list_workflows())

    assert set(BUILT_INS) <= set(names)
    assert scheduler.workflow_registry.validate_workflow("feature-development")

    scheduler.workflow_registry.unregister_workflow("bug-fix")

    assert "bug-fix" not in {workflow.name for workflow in scheduler.workflow_registry.list_workflows()}


def test_feature_development_composes_documentation_and_code_review_workflows():
    scheduler = Scheduler.default()
    workflow = scheduler.workflow_registry.load_workflow("feature-development")
    task = scheduler.run_workflow("feature-development", "Implement JWT authentication", {"max_retries": 2})

    step_ids = [step["id"] for step in task.metadata["last_plan"]["steps"]]

    assert any(step_id.startswith("documentation.") for step_id in step_ids)
    assert any(step_id.startswith("review.") for step_id in step_ids)
    assert "complete" in step_ids
    assert workflow.metadata["title"] == "Feature Development"


def test_workflow_parameters_render_into_steps_and_retry_policy():
    scheduler = Scheduler.default()
    result = scheduler.run_workflow(
        "test-generation",
        "Generate tests for parser",
        {"coverage_target": 95, "max_retries": 4},
    )

    steps = result.metadata["last_plan"]["steps"]
    coverage_step = next(step for step in steps if step["id"] == "coverage-check")
    generate_tests = next(step for step in steps if step["id"] == "generate-tests")

    assert "95" in coverage_step["description"]
    assert generate_tests["retry_policy"]["max_attempts"] == 2


def test_workflow_import_export_json_and_yaml(tmp_path):
    workflow = EngineeringWorkflowDefinition(
        name="custom-workflow",
        metadata={"title": "Custom"},
        parameters={"max_retries": 2},
        outputs=["documentation"],
        steps=[
            WorkflowStepSpec(
                id="analyze",
                description="Analyze {goal}",
                capability="architecture",
                expected_artifacts=["documentation"],
            )
        ],
    )
    json_path = tmp_path / "workflow.json"
    yaml_path = tmp_path / "workflow.yaml"

    workflow.export(json_path)
    workflow.export(yaml_path)
    from_json = EngineeringWorkflowDefinition.load(json_path)
    from_yaml = EngineeringWorkflowDefinition.load(yaml_path)

    assert from_json.to_dict() == workflow.to_dict()
    assert from_yaml.to_dict() == workflow.to_dict()

    scheduler = Scheduler.default()
    scheduler.workflow_registry.import_workflow(json_path)
    exported = tmp_path / "exported.yaml"
    scheduler.workflow_registry.export_workflow("custom-workflow", exported)

    assert EngineeringWorkflowDefinition.load(exported).to_dict() == workflow.to_dict()


def test_custom_workflow_registration_and_execution():
    scheduler = Scheduler.default()
    workflow = EngineeringWorkflowDefinition(
        name="custom-docs",
        metadata={"title": "Custom Docs"},
        steps=[
            WorkflowStepSpec(id="docs", description="Document {goal}", capability="documentation", expected_artifacts=["documentation"])
        ],
        outputs=["documentation"],
    )
    scheduler.workflow_registry.register_workflow(workflow)

    result = scheduler.run_workflow("custom-docs", "Document adapter contracts")

    assert result.status == TaskStatus.DONE
    assert result.metadata["last_plan"]["metadata"]["workflow"] == "custom-docs"


def test_invalid_workflow_validation_rejects_unknown_dependency():
    workflow = EngineeringWorkflowDefinition(
        name="invalid",
        metadata={},
        steps=[WorkflowStepSpec(id="step", description="bad", capability="coding", dependencies=["missing"])],
    )

    with pytest.raises(ValueError):
        workflow.validate()


class FlakyAdapter(MockAgentAdapter):
    def __init__(self):
        super().__init__(name="mock.flaky", capabilities=["coding"])
        self.calls = 0

    def execute(self, step, context):
        self.calls += 1
        if self.calls == 1:
            session = context.start_agent_session(self.provider, self.model, step.id, context.current_workflow)
            context.finish_agent_session(session.id, failed=True)
            return AgentResponse(
                status=AgentResponseStatus.FAILED,
                reasoning_summary="first call fails",
                errors=["transient"],
                session_id=session.id,
            )
        return super().execute(step, context)


def test_workflow_retry_replans_failed_subtree_and_succeeds():
    scheduler = Scheduler.default()
    scheduler.agent_registry.unregister_adapter("mock.agent")
    scheduler.agent_registry.register_adapter(FlakyAdapter())
    workflow = EngineeringWorkflowDefinition(
        name="retry-workflow",
        metadata={"title": "Retry"},
        steps=[
            WorkflowStepSpec(
                id="patch",
                description="Patch {goal}",
                capability="coding",
                expected_artifacts=["implementation"],
                retry_policy=RetryPolicy(max_attempts=2),
            )
        ],
    )
    scheduler.workflow_registry.register_workflow(workflow)

    result = scheduler.run_workflow("retry-workflow", "Retry transient coding failure", {"max_retries": 2})

    assert result.status == TaskStatus.DONE
    assert EventType.PLAN_REVISED in {event.type for event in scheduler.event_bus.list()}
    assert result.metadata["last_execution"]["metrics"]["counters"]["plan_revisions"] == 1


def test_workflow_visualization_contains_dag_timeline_artifacts_and_metrics():
    scheduler = Scheduler.default()
    result = scheduler.run_workflow("documentation", "Document workflow library")

    visualization = result.metadata["workflow_visualization"]["content"]

    assert visualization["dag"]["nodes"]
    assert visualization["dag"]["edges"]
    assert visualization["timeline"]
    assert "artifact_graph" in visualization
    assert visualization["metrics"]["critical_path"]
