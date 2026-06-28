from __future__ import annotations

from core.execution import ExecutionContext
from core.planning import ExecutionPlan
from core.registries import SkillRegistry
from core.workflow.graph import FunctionNode, NodeResult, WorkflowDefinition
from core.workflow.plan_executor import PlanWorkflowExecutor


class DynamicWorkflowBuilder:
    name = "dynamic.workflow_builder"

    def __init__(self, executor: PlanWorkflowExecutor) -> None:
        self.executor = executor

    def build(self, plan: ExecutionPlan) -> WorkflowDefinition:
        def execute_plan(context: ExecutionContext) -> NodeResult:
            result = self.executor.execute(plan, context)
            return NodeResult(context=result.context, completed=result.success, failed=not result.success)

        return WorkflowDefinition(
            name=f"plan_{plan.id}",
            start_node="execute_plan",
            nodes={"execute_plan": FunctionNode("execute_plan", execute_plan)},
        )

