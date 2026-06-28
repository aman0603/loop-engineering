from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from core.artifacts import Artifact
from core.decision import Decision, DecisionEngine
from core.events import Event, EventType
from core.execution import ExecutionContext
from core.planning import ExecutionStep, PlanStatus, PlannerEngine
from core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from core.workflow.graph import NodeResult
from verification import VerificationPipeline


StepHandler = Callable[[ExecutionContext, ExecutionStep], bool]
BranchPredicate = Callable[[ExecutionContext], bool]


class BaseWorkflowNode:
    def __init__(self, name: str) -> None:
        self.name = name

    def run(self, context: ExecutionContext) -> NodeResult:
        return NodeResult(context=context)


class PlanningNode(BaseWorkflowNode):
    def __init__(
        self,
        planner: PlannerEngine,
        skills: SkillRegistry,
        tools: ToolRegistry,
        agents: AgentRegistry,
    ) -> None:
        super().__init__("planning")
        self.planner = planner
        self.skills = skills
        self.tools = tools
        self.agents = agents

    def run(self, context: ExecutionContext) -> NodeResult:
        self.planner.plan(context.task, context, self.skills, self.tools, self.agents)
        return NodeResult(context=context)


class SkillStepNode(BaseWorkflowNode):
    def __init__(self, step: ExecutionStep, skills: SkillRegistry) -> None:
        super().__init__(step.id)
        self.step = step
        self.skills = skills

    def run(self, context: ExecutionContext) -> NodeResult:
        if not self.step.required_skill:
            context.log(self.name, self.step.description, step_id=self.step.id)
            return NodeResult(context=context)
        skill = self.skills.get(self.step.required_skill)
        context.current_skill = skill.name
        result = skill.execute(context)
        for artifact in result.artifacts:
            context.add_artifact(artifact)
        if result.output:
            context.merge_artifacts(result.output, producer=skill.name)
        for message in result.logs:
            context.log(skill.name, message, step_id=self.step.id)
        if not result.success:
            context.record_error(skill.name, "plan step skill failed", step_id=self.step.id, errors=result.errors)
            return NodeResult(context=context, failed=True)
        return NodeResult(context=context)


class ResearchNode(SkillStepNode):
    pass


class ImplementationNode(SkillStepNode):
    pass


class TestingNode(SkillStepNode):
    pass


class DocumentationNode(SkillStepNode):
    pass


class ReviewNode(SkillStepNode):
    pass


class VerificationNode(BaseWorkflowNode):
    def __init__(self, verification: VerificationPipeline) -> None:
        super().__init__("verification")
        self.verification = verification

    def run(self, context: ExecutionContext) -> NodeResult:
        report = self.verification.run(context)
        context.runtime_variables["last_verification_report"] = report
        return NodeResult(context=context, failed=not report.passed)


@dataclass(frozen=True, slots=True)
class BranchRule:
    name: str
    predicate: BranchPredicate
    target: str


class DecisionNode(BaseWorkflowNode):
    def __init__(self, rules: list[BranchRule] | None = None, default_target: str | None = None) -> None:
        super().__init__("decision")
        self.rules = rules or []
        self.default_target = default_target

    def run(self, context: ExecutionContext) -> NodeResult:
        for rule in self.rules:
            if rule.predicate(context):
                context.emit(Event(EventType.BRANCH_SELECTED, context.task.id, {"rule": rule.name, "target": rule.target}))
                return NodeResult(context=context, next_node=rule.target)
        if self.default_target:
            context.emit(Event(EventType.BRANCH_SELECTED, context.task.id, {"rule": "default", "target": self.default_target}))
            return NodeResult(context=context, next_node=self.default_target)
        return NodeResult(context=context)


class HumanApprovalNode(BaseWorkflowNode):
    def __init__(self, approval_key: str) -> None:
        super().__init__("human_approval")
        self.approval_key = approval_key

    def run(self, context: ExecutionContext) -> NodeResult:
        approved = bool(context.runtime_variables.get(self.approval_key))
        return NodeResult(context=context, pause_requested=not approved, failed=False)


class PlanStepNode(BaseWorkflowNode):
    def __init__(
        self,
        step: ExecutionStep,
        skills: SkillRegistry,
        agents: AgentRegistry | None = None,
        handler: StepHandler | None = None,
    ) -> None:
        super().__init__(step.id)
        self.step = step
        self.skills = skills
        self.agents = agents
        self.handler = handler

    def run(self, context: ExecutionContext) -> NodeResult:
        context.emit(Event(EventType.PLAN_STEP_STARTED, context.task.id, {"step_id": self.step.id}))
        self.step.status = PlanStatus.RUNNING
        self.step.attempts += 1
        ok = self.handler(context, self.step) if self.handler else self._run_default(context)
        self.step.status = PlanStatus.COMPLETED if ok else PlanStatus.FAILED
        context.emit(
            Event(
                EventType.PLAN_STEP_FINISHED,
                context.task.id,
                {"step_id": self.step.id, "success": ok, "attempts": self.step.attempts},
            )
        )
        return NodeResult(context=context, failed=not ok)

    def _run_default(self, context: ExecutionContext) -> bool:
        if self.agents is not None:
            adapter_result = AgentAdapterStepNode(self.step, self.agents).run(context)
            if not adapter_result.failed:
                return True
            if self.step.required_skill is None:
                return False

        result = SkillStepNode(self.step, self.skills).run(context)
        if result.failed:
            return False
        for artifact_type in self.step.expected_artifacts:
            if artifact_type not in context.artifact_store:
                context.add_artifact(Artifact(artifact_type, self.name, {"step_id": self.step.id}))
        return True


class AgentAdapterStepNode(BaseWorkflowNode):
    def __init__(self, step: ExecutionStep, agents: AgentRegistry) -> None:
        super().__init__(step.id)
        self.step = step
        self.agents = agents

    def run(self, context: ExecutionContext) -> NodeResult:
        capability = self.step.required_capability or self.step.metadata.get("capability") or self.step.required_skill
        adapter_name = self.step.metadata.get("adapter")
        adapter = self.agents.get_adapter(adapter_name) if adapter_name else None
        if adapter is None and capability:
            adapter = self.agents.find_adapter_for_capability(str(capability))
        if adapter is None:
            context.record_error(self.name, "no adapter available", capability=capability)
            return NodeResult(context=context, failed=True)

        tried: set[str] = set()
        max_attempts = max(1, self.step.retry_policy.max_attempts)
        for attempt in range(max_attempts):
            context.emit(Event(EventType.AGENT_STARTED, context.task.id, {"adapter": adapter.name, "step_id": self.step.id}))
            adapter.initialize(context)
            response = adapter.execute(self.step, context)
            if response.session_id:
                context.runtime_variables["last_agent_session_id"] = response.session_id
            if response.success:
                for artifact in response.artifacts:
                    if context.artifact_store.get(artifact.id) is None:
                        context.add_artifact(artifact)
                context.emit(
                    Event(
                        EventType.AGENT_FINISHED,
                        context.task.id,
                        {"adapter": adapter.name, "step_id": self.step.id, "session_id": response.session_id},
                    )
                )
                return NodeResult(context=context)

            tried.add(adapter.name)
            context.record_error(adapter.name, "agent adapter failed", step_id=self.step.id, errors=response.errors)
            context.emit(
                Event(
                    EventType.AGENT_FAILED,
                    context.task.id,
                    {"adapter": adapter.name, "step_id": self.step.id, "errors": response.errors, "attempt": attempt + 1},
                )
            )
            replacement = self.agents.find_adapter_for_capability(str(capability), exclude=tried) if capability else None
            decision = DecisionEngine().decide_recovery(
                context,
                {
                    "kind": "agent_adapter",
                    "adapter": adapter.name,
                    "step_id": self.step.id,
                    "attempts": attempt + 1,
                    "max_attempts": max_attempts,
                    "replacement_available": replacement is not None,
                },
            )
            context.emit(
                Event(
                    EventType.DECISION_MADE,
                    context.task.id,
                    {"decision": decision.decision.value, "reason": decision.reason, **decision.metadata},
                )
            )
            if replacement is not None:
                adapter = replacement
                self.step.metadata["adapter"] = adapter.name
                continue
            if decision.decision != Decision.RETRY:
                break
        return NodeResult(context=context, failed=True)


class AdaptiveReplanningNode(BaseWorkflowNode):
    def __init__(self, planner: PlannerEngine) -> None:
        super().__init__("adaptive_replanning")
        self.planner = planner

    def run(self, context: ExecutionContext) -> NodeResult:
        plan = context.runtime_variables.get("execution_plan")
        failed_step_id = context.runtime_variables.get("failed_step_id")
        if plan is None or not failed_step_id:
            return NodeResult(context=context, failed=True)
        self.planner.replan_failed_subtree(plan, failed_step_id, context)
        return NodeResult(context=context)


class PlanDecisionNode(BaseWorkflowNode):
    def __init__(self, decision_engine: DecisionEngine | None = None) -> None:
        super().__init__("plan_decision")
        self.decision_engine = decision_engine or DecisionEngine()

    def run(self, context: ExecutionContext) -> NodeResult:
        report = context.runtime_variables.get("last_verification_report")
        decision = self.decision_engine.decide(context, report)
        context.runtime_variables["last_decision"] = decision
        context.emit(
            Event(
                EventType.DECISION_MADE,
                context.task.id,
                {"decision": decision.decision.value, "reason": decision.reason, **decision.metadata},
            )
        )
        return NodeResult(context=context, completed=decision.decision == Decision.COMPLETE, failed=decision.decision == Decision.ABORT)
