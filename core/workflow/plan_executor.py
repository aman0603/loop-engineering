from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable

from core.decision import Decision, DecisionEngine
from core.events import Event, EventType
from core.execution import ExecutionContext
from core.planning import ExecutionPlan, ExecutionStep, PlanStatus, PlannerEngine
from core.registries import AgentRegistry, SkillRegistry
from core.workflow.nodes import PlanStepNode, StepHandler


@dataclass(slots=True)
class PlanExecutionResult:
    context: ExecutionContext
    completed_steps: set[str] = field(default_factory=set)
    failed_step_id: str | None = None
    replanned: bool = False

    @property
    def success(self) -> bool:
        return self.failed_step_id is None


class PlanWorkflowExecutor:
    name = "plan.workflow_executor"

    def __init__(
        self,
        skills: SkillRegistry,
        agents: AgentRegistry | None = None,
        decision_engine: DecisionEngine | None = None,
        planner: PlannerEngine | None = None,
        step_handlers: dict[str, StepHandler] | None = None,
        max_workers: int = 4,
    ) -> None:
        self.skills = skills
        self.agents = agents
        self.decision_engine = decision_engine or DecisionEngine()
        self.planner = planner or PlannerEngine()
        self.step_handlers = step_handlers or {}
        self.max_workers = max_workers

    def execute(self, plan: ExecutionPlan, context: ExecutionContext) -> PlanExecutionResult:
        started = time.monotonic()
        context.runtime_variables["execution_plan"] = plan
        completed: set[str] = set(context.runtime_variables.get("completed_plan_steps", set()))
        blocked: set[str] = set()
        failed_step_id: str | None = None

        for index, group in enumerate(plan.parallel_groups()):
            ready_group = [step for step in group if step.id not in completed and set(step.dependencies) <= completed]
            if not ready_group:
                continue
            context.emit(Event(EventType.PARALLEL_GROUP_STARTED, context.task.id, {"index": index, "steps": [s.id for s in ready_group]}))
            group_results = self._execute_group(ready_group, context)
            context.emit(Event(EventType.PARALLEL_GROUP_FINISHED, context.task.id, {"index": index, "results": group_results}))

            for step_id, ok in group_results.items():
                if ok:
                    completed.add(step_id)
                else:
                    failed_step_id = step_id
                    blocked.update(plan.descendants(step_id))
                    break
            if failed_step_id:
                break

        context.runtime_variables["completed_plan_steps"] = completed
        context.metrics.set("planning.execution_efficiency", len(completed) / max(len(plan.steps), 1))
        context.metrics.record_timing("planning.plan_execution_time_ms", (time.monotonic() - started) * 1000)

        if failed_step_id:
            context.runtime_variables["failed_step_id"] = failed_step_id
            decision = self.decision_engine.decide_recovery(
                context,
                {"kind": "plan_step", "step_id": failed_step_id, "attempts": plan.step_map[failed_step_id].attempts},
            )
            context.emit(
                Event(
                    EventType.DECISION_MADE,
                    context.task.id,
                    {"decision": decision.decision.value, "reason": decision.reason, **decision.metadata},
                )
            )
            if decision.decision == Decision.RETRY and plan.step_map[failed_step_id].attempts < plan.step_map[failed_step_id].retry_policy.max_attempts:
                replanned = self.planner.replan_failed_subtree(plan, failed_step_id, context)
                subtree_result = self.execute(replanned, context)
                return PlanExecutionResult(context, completed | subtree_result.completed_steps, subtree_result.failed_step_id, replanned=True)
            return PlanExecutionResult(context, completed, failed_step_id, replanned=False)

        return PlanExecutionResult(context, completed, None, False)

    def _execute_group(self, group: list[ExecutionStep], context: ExecutionContext) -> dict[str, bool]:
        if len(group) == 1:
            step = group[0]
            return {step.id: self._execute_step(step, context)}
        results: dict[str, bool] = {}
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(group))) as executor:
            future_map = {executor.submit(self._execute_step, step, context): step.id for step in group}
            for future in as_completed(future_map):
                step_id = future_map[future]
                try:
                    results[step_id] = bool(future.result())
                except Exception as exc:  # pragma: no cover - defensive boundary for arbitrary step handlers
                    context.record_error(self.name, str(exc), step_id=step_id)
                    results[step_id] = False
        return results

    def _execute_step(self, step: ExecutionStep, context: ExecutionContext) -> bool:
        handler = self.step_handlers.get(step.id) or self.step_handlers.get(step.required_capability or "")
        result = PlanStepNode(step, self.skills, self.agents, handler).run(context)
        return not result.failed
