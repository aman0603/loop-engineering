from __future__ import annotations

from pathlib import Path

from agents.coder import CodingAgent
from agents.planner import PlannerAgent
from agents.adapters import MockAgentAdapter
from core.config import ExecutionConfig
from core.events import Event, EventBus, EventType, InMemoryEventBus
from core.execution import ExecutionContext
from core.feedback import FeedbackEngine
from core.planning import ExecutionPlan, PlannerEngine
from core.registries import AgentRegistry, SkillRegistry, ToolRegistry, VerifierRegistry, WorkflowRegistry
from core.scheduler.queue import TaskPriorityQueue
from core.task_manager import InMemoryTaskRepository, Task, TaskRepository, TaskStatus
from core.workflow import DefaultEngineeringWorkflowFactory, DynamicWorkflowBuilder, PlanWorkflowExecutor, WorkflowEngine
from skills.coding import CodingSkill
from skills.planning import PlanningSkill
from tools import FileSystemTool, GitTool, HTTPTool, PythonTool, SearchTool, ShellTool, TestTool
from verification import VerificationPipeline
from worktree import WorktreeManager


class WorkflowSelector:
    def select(self, task: Task) -> str:
        return str(task.metadata.get("workflow", "default_engineering"))


class Scheduler:
    def __init__(
        self,
        repository: TaskRepository,
        workflow_registry: WorkflowRegistry,
        workflow_engine: WorkflowEngine | None = None,
        selector: WorkflowSelector | None = None,
        event_bus: EventBus | None = None,
        queue: TaskPriorityQueue | None = None,
        agent_registry: AgentRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        verifier_registry: VerifierRegistry | None = None,
        tool_registry: ToolRegistry | None = None,
        worktree_manager: WorktreeManager | None = None,
        planner_engine: PlannerEngine | None = None,
    ) -> None:
        self.repository = repository
        self.workflow_registry = workflow_registry
        self.workflow_engine = workflow_engine or WorkflowEngine()
        self.selector = selector or WorkflowSelector()
        self.event_bus = event_bus or InMemoryEventBus()
        self.queue = queue or TaskPriorityQueue()
        self.agent_registry = agent_registry or AgentRegistry()
        self.skill_registry = skill_registry or SkillRegistry()
        self.verifier_registry = verifier_registry or VerifierRegistry()
        self.tool_registry = tool_registry or ToolRegistry()
        self.worktree_manager = worktree_manager
        self.planner_engine = planner_engine or PlannerEngine()

    @classmethod
    def default(cls) -> "Scheduler":
        event_bus = InMemoryEventBus()
        skill_registry = SkillRegistry()
        planning_skill = PlanningSkill()
        coding_skill = CodingSkill()
        skill_registry.register(planning_skill)
        skill_registry.register(coding_skill)

        agent_registry = AgentRegistry()
        planner = PlannerAgent(planning_skill)
        coder = CodingAgent(coding_skill)
        agent_registry.register(planner)
        agent_registry.register(coder)
        agent_registry.register_adapter(MockAgentAdapter())

        verifier_registry = VerifierRegistry()
        verification = VerificationPipeline()
        for check in verification.checks:
            verifier_registry.register(check)

        registry = WorkflowRegistry()
        workflow = DefaultEngineeringWorkflowFactory(
            planner=agent_registry.get("planner"),
            coder=agent_registry.get("coder"),
            verification=verification,
            feedback=FeedbackEngine(),
            event_bus=event_bus,
        ).build()
        registry.register(workflow)
        tool_registry = ToolRegistry()
        for tool in [ShellTool(), FileSystemTool(), GitTool(), PythonTool(), TestTool(), SearchTool(), HTTPTool()]:
            tool_registry.register(tool)

        return cls(
            repository=InMemoryTaskRepository(),
            workflow_registry=registry,
            event_bus=event_bus,
            agent_registry=agent_registry,
            skill_registry=skill_registry,
            verifier_registry=verifier_registry,
            tool_registry=tool_registry,
        )

    @classmethod
    def runtime_default(
        cls,
        repository: str | Path,
        worktree_root: str | Path | None = None,
    ) -> "Scheduler":
        scheduler = cls.default()
        scheduler.worktree_manager = WorktreeManager(repository, root=worktree_root)
        return scheduler

    def create_execution_plan(self, task: Task, context: ExecutionContext | None = None) -> ExecutionPlan:
        planning_context = context or ExecutionContext(task=task, event_bus=self.event_bus)
        return self.planner_engine.plan(
            task,
            planning_context,
            self.skill_registry,
            self.tool_registry,
            self.agent_registry,
        )

    def run_planned(self, task: Task, plan: ExecutionPlan | None = None) -> Task:
        if self.repository.get(task.id) is None:
            self.repository.save(task)
        context = ExecutionContext(
            task=task,
            configuration=ExecutionConfig(retry_limit=task.max_attempts, workflow_name="dynamic_plan"),
            current_workflow="dynamic_plan",
            event_bus=self.event_bus,
        )
        execution_plan = plan or self.create_execution_plan(task, context)
        workflow = DynamicWorkflowBuilder(
            PlanWorkflowExecutor(skills=self.skill_registry, agents=self.agent_registry, planner=self.planner_engine)
        ).build(execution_plan)
        worktree = None
        try:
            if self.worktree_manager is not None:
                worktree = self.worktree_manager.create_worktree(context)
            execution = self.workflow_engine.run(workflow, context)
        finally:
            if worktree is not None and self.worktree_manager is not None:
                self.worktree_manager.cleanup_worktree(context, worktree, force=True)
        finished_task = execution.context.task
        if execution.status.value == "COMPLETED" and finished_task.status == TaskStatus.NEW:
            finished_task.transition_to(TaskStatus.PLANNING)
            finished_task.transition_to(TaskStatus.EXECUTING)
            finished_task.transition_to(TaskStatus.VERIFYING)
            finished_task.transition_to(TaskStatus.DONE)
        elif execution.status.value != "COMPLETED" and finished_task.status == TaskStatus.NEW:
            finished_task.transition_to(TaskStatus.FAILED)
        finished_task.metadata["last_execution"] = execution.context.observability_snapshot()
        finished_task.metadata["last_plan"] = execution_plan.to_dict()
        self.repository.save(finished_task)
        if execution.status.value == "COMPLETED":
            self.event_bus.publish(Event(EventType.TASK_COMPLETED, finished_task.id, {"plan_id": execution_plan.id}))
        else:
            self.event_bus.publish(Event(EventType.TASK_FAILED, finished_task.id, {"plan_id": execution_plan.id}))
        return finished_task

    def submit(self, task: Task) -> None:
        if task.status != TaskStatus.NEW:
            raise ValueError("only NEW tasks can be submitted")
        self.repository.save(task)
        self.queue.push(task)
        self.event_bus.publish(Event(EventType.TASK_CREATED, task.id, {"title": task.title}))
        self.event_bus.publish(Event(EventType.TASK_SCHEDULED, task.id, {"priority": task.priority}))

    def run_next(self) -> Task | None:
        task = self._pop_available_task()
        if task is None:
            return None

        workflow_name = self.selector.select(task)
        self.event_bus.publish(Event(EventType.TASK_STARTED, task.id, {"attempts": task.attempts}))
        definition = self.workflow_registry.get(workflow_name)
        context = ExecutionContext(
            task=task,
            configuration=ExecutionConfig(retry_limit=task.max_attempts, workflow_name=workflow_name),
            current_workflow=workflow_name,
            event_bus=self.event_bus,
        )
        worktree = None
        try:
            if self.worktree_manager is not None:
                worktree = self.worktree_manager.create_worktree(context)
            execution = self.workflow_engine.run(definition, context)
        finally:
            if worktree is not None and self.worktree_manager is not None:
                self.worktree_manager.cleanup_worktree(context, worktree, force=True)
        finished_task = execution.context.task
        finished_task.metadata["last_execution"] = execution.context.observability_snapshot()
        self.repository.save(finished_task)

        if finished_task.status == TaskStatus.DONE:
            self.event_bus.publish(
                Event(EventType.TASK_COMPLETED, finished_task.id, {"visited_nodes": execution.visited_nodes})
            )
        elif finished_task.status == TaskStatus.FAILED:
            self.event_bus.publish(
                Event(EventType.TASK_FAILED, finished_task.id, {"visited_nodes": execution.visited_nodes})
            )
        return finished_task

    def run_all(self) -> list[Task]:
        completed: list[Task] = []
        while len(self.queue) > 0:
            task = self.run_next()
            if task is None:
                break
            completed.append(task)
        return completed

    def _pop_available_task(self) -> Task | None:
        deferred: list[Task] = []
        selected: Task | None = None

        while len(self.queue) > 0:
            task_id = self.queue.pop()
            if task_id is None:
                break
            task = self.repository.get(task_id)
            if task is None:
                continue
            if self._dependencies_satisfied(task):
                selected = task
                break
            deferred.append(task)

        for task in deferred:
            self.queue.push(task)
        return selected

    def _dependencies_satisfied(self, task: Task) -> bool:
        for dependency_id in task.dependencies:
            dependency = self.repository.get(dependency_id)
            if dependency is None or dependency.status != TaskStatus.DONE:
                return False
        return True
