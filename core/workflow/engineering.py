from __future__ import annotations

from agents.base import Agent
from core.decision import Decision, DecisionEngine, DecisionResult
from core.events import Event, EventBus, EventType, InMemoryEventBus
from core.execution import ExecutionContext
from core.feedback import FeedbackEngine
from core.state_machine import StateMachine, WorkflowState
from core.workflow.graph import FunctionNode, NodeResult, WorkflowDefinition
from verification import VerificationPipeline


class DefaultEngineeringWorkflowFactory:
    def __init__(
        self,
        planner: Agent,
        coder: Agent,
        verification: VerificationPipeline,
        feedback: FeedbackEngine,
        event_bus: EventBus | None = None,
        decision_engine: DecisionEngine | None = None,
        state_machine: StateMachine | None = None,
    ) -> None:
        self.planner = planner
        self.coder = coder
        self.verification = verification
        self.feedback = feedback
        self.event_bus = event_bus or InMemoryEventBus()
        self.decision_engine = decision_engine or DecisionEngine()
        self.state_machine = state_machine or StateMachine()
        self._decision_handlers = {
            Decision.COMPLETE: self._complete,
            Decision.RETRY: self._retry,
            Decision.ABORT: self._abort,
            Decision.CHANGE_SKILL: self._abort,
            Decision.CHANGE_AGENT: self._abort,
            Decision.ESCALATE: self._abort,
        }

    def build(self) -> WorkflowDefinition:
        return WorkflowDefinition(
            name="default_engineering",
            start_node="plan",
            nodes={
                "plan": FunctionNode("plan", self._plan),
                "code": FunctionNode("code", self._code),
                "verify": FunctionNode("verify", self._verify),
            },
        )

    def _plan(self, context: ExecutionContext) -> NodeResult:
        task = context.task
        if context.workflow_state is None:
            self.state_machine.transition_for_event(context, "plan")

        context.emit(Event(EventType.PLANNING_STARTED, task.id, {"agent": self.planner.name}))
        self._agent_event(context, EventType.AGENT_STARTED, self.planner.name)
        result = self.planner.handle(context)
        self._agent_event(context, EventType.AGENT_FINISHED, self.planner.name, {"success": result.success})
        context.emit(Event(EventType.PLANNING_COMPLETED, task.id, {"success": result.success}))
        if not result.success:
            self.state_machine.transition_for_event(context, "fail")
            context.record_error(self.planner.name, "planning failed", errors=result.errors)
            return NodeResult(context=context, failed=True)

        task.assigned_agent = self.coder.name
        return NodeResult(context=context, next_node="code")

    def _code(self, context: ExecutionContext) -> NodeResult:
        task = context.task
        self.state_machine.transition_for_event(context, "implement")
        task.attempts += 1
        context.retry_count = task.attempts

        self._agent_event(context, EventType.AGENT_STARTED, self.coder.name)
        result = self.coder.handle(context)
        self._agent_event(context, EventType.AGENT_FINISHED, self.coder.name, {"success": result.success})
        if not result.success:
            self.state_machine.transition_for_event(context, "fail")
            context.record_error(self.coder.name, "coding failed", errors=result.errors)
            return NodeResult(context=context, failed=True)

        return NodeResult(context=context, next_node="verify")

    def _verify(self, context: ExecutionContext) -> NodeResult:
        task = context.task
        self.state_machine.transition_for_event(context, "verify")
        report = self.verification.run(context)
        task.metrics.update(report.metrics)

        if not report.passed:
            feedback = self.feedback.from_verification(report)
            context.feedback = feedback
            task.metadata["last_feedback"] = [item.to_dict() for item in feedback]

        decision = self.decision_engine.decide(context, report)
        context.runtime_variables["last_decision"] = decision
        context.emit(
            Event(
                EventType.DECISION_MADE,
                task.id,
                {"decision": decision.decision.value, "reason": decision.reason, **decision.metadata},
            )
        )
        return self._decision_handlers[decision.decision](context, decision)

    def _agent_event(
        self,
        context: ExecutionContext,
        event_type: EventType,
        agent: str,
        payload: dict | None = None,
    ) -> None:
        context.emit(Event(event_type, context.task.id, {"agent": agent, **(payload or {})}))

    def _complete(self, context: ExecutionContext, decision: DecisionResult) -> NodeResult:
        self.state_machine.transition_for_event(context, "complete")
        return NodeResult(context=context, completed=True)

    def _retry(self, context: ExecutionContext, decision: DecisionResult) -> NodeResult:
        self.state_machine.transition_for_event(context, "fail")
        self.state_machine.transition_for_event(context, "retry")
        context.metrics.increment("retries")
        context.emit(
            Event(
                EventType.RETRY_REQUESTED,
                context.task.id,
                {"retry_count": context.retry_count, "reason": decision.reason},
            )
        )
        return NodeResult(context=context, next_node="plan")

    def _abort(self, context: ExecutionContext, decision: DecisionResult) -> NodeResult:
        if context.workflow_state != WorkflowState.FAILED.value:
            self.state_machine.transition_for_event(context, "fail")
        self.state_machine.transition_for_event(context, "abort")
        context.record_error("decision_engine", decision.reason, decision=decision.decision.value)
        return NodeResult(context=context, failed=True)
