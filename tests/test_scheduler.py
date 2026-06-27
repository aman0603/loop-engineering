from core.events import EventType, InMemoryEventBus
from core.feedback import FeedbackEngine
from core.scheduler import Scheduler, WorkflowRegistry
from core.task_manager import InMemoryTaskRepository, Task, TaskStatus, VerificationOutcome, VerificationResult, utc_now
from core.workflow import DefaultEngineeringWorkflowFactory
from agents.coder import CodingAgent
from agents.planner import PlannerAgent
from verification import VerificationCheck, VerificationPipeline


class PassOnSecondAttemptCheck(VerificationCheck):
    name = "test.pass_on_second_attempt"

    def run(self, task, context):
        started_at = utc_now()
        implementation = context.artifacts.get("implementation", {})
        passed = implementation.get("revision", 0) >= 2
        return VerificationResult(
            name=self.name,
            outcome=VerificationOutcome.PASSED if passed else VerificationOutcome.FAILED,
            summary="passed on revised implementation" if passed else "first implementation failed",
            started_at=started_at,
            finished_at=utc_now(),
        )


class AlwaysFailCheck(VerificationCheck):
    name = "test.always_fail"

    def run(self, task, context):
        started_at = utc_now()
        return VerificationResult(
            name=self.name,
            outcome=VerificationOutcome.FAILED,
            summary="verification never passes",
            started_at=started_at,
            finished_at=utc_now(),
        )


def scheduler_with_checks(checks):
    event_bus = InMemoryEventBus()
    registry = WorkflowRegistry()
    registry.register(
        DefaultEngineeringWorkflowFactory(
            planner=PlannerAgent(),
            coder=CodingAgent(),
            verification=VerificationPipeline(checks),
            feedback=FeedbackEngine(),
            event_bus=event_bus,
        ).build()
    )
    return Scheduler(
        repository=InMemoryTaskRepository(),
        workflow_registry=registry,
        event_bus=event_bus,
    )


def test_default_scheduler_completes_a_task():
    scheduler = Scheduler.default()
    task = Task(
        title="Generate docs",
        description="Create documentation",
        goal="Docs exist",
        acceptance_criteria=["Docs cover setup"],
    )

    scheduler.submit(task)
    result = scheduler.run_next()

    assert result is not None
    assert result.status == TaskStatus.DONE
    assert result.attempts == 1
    assert {event.type for event in scheduler.event_bus.list()} >= {
        EventType.TASK_CREATED,
        EventType.TASK_STARTED,
        EventType.VERIFICATION_PASSED,
        EventType.TASK_COMPLETED,
    }


def test_failed_verification_creates_feedback_and_retries_with_replanning():
    scheduler = scheduler_with_checks([PassOnSecondAttemptCheck()])
    task = Task(title="Feature", description="Build it", goal="It works", max_attempts=3)

    scheduler.submit(task)
    result = scheduler.run_next()

    assert result is not None
    assert result.status == TaskStatus.DONE
    assert result.attempts == 2
    assert result.metadata["last_feedback"][0]["summary"] == "first implementation failed"
    assert any(log.message == "created plan with 5 steps" for log in result.execution_logs)
    assert [event.type for event in scheduler.event_bus.list()].count(EventType.VERIFICATION_FAILED) == 1


def test_retry_limit_stops_failed_task():
    scheduler = scheduler_with_checks([AlwaysFailCheck()])
    task = Task(title="Feature", description="Build it", goal="It works", max_attempts=2)

    scheduler.submit(task)
    result = scheduler.run_next()

    assert result is not None
    assert result.status == TaskStatus.FAILED
    assert result.attempts == 2
    assert [event.type for event in scheduler.event_bus.list()].count(EventType.VERIFICATION_FAILED) == 2


def test_scheduler_respects_priority_and_dependencies():
    scheduler = Scheduler.default()
    dependency = Task(title="Dependency", description="First", goal="Done", priority=50)
    dependent = Task(
        title="Dependent",
        description="Second",
        goal="Done",
        priority=0,
        dependencies=[dependency.id],
    )

    scheduler.submit(dependent)
    scheduler.submit(dependency)
    first = scheduler.run_next()
    second = scheduler.run_next()

    assert first is not None
    assert second is not None
    assert first.id == dependency.id
    assert second.id == dependent.id
    assert second.status == TaskStatus.DONE

