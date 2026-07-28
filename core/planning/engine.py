from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable

from core.artifacts import PlanArtifact
from core.events import Event, EventType
from core.execution import ExecutionContext
from core.planning.plan import ExecutionPlan, ExecutionStep, RetryPolicy
from core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from core.task_manager import Task


@dataclass(frozen=True, slots=True)
class SkillCandidate:
    name: str
    score: float
    reasons: list[str]


class SkillSelector:
    def select(
        self,
        required_capability: str,
        available_skills: SkillRegistry,
        available_tools: ToolRegistry,
        context: ExecutionContext,
    ) -> SkillCandidate:
        candidates = self.rank(required_capability, available_skills, available_tools, context)
        if not candidates:
            raise ValueError(f"no skill available for capability '{required_capability}'")
        return candidates[0]

    def rank(
        self,
        required_capability: str,
        available_skills: SkillRegistry,
        available_tools: ToolRegistry,
        context: ExecutionContext,
    ) -> list[SkillCandidate]:
        ranked: list[SkillCandidate] = []
        tool_names = set(available_tools.names())
        history = context.execution_metadata.get("skill_history", {})
        for skill in available_skills.list():
            metadata = getattr(skill, "metadata", {})
            capabilities = set(metadata.get("capabilities", []))
            required_tools = set(metadata.get("tools", []))
            skill_name = getattr(skill, "name")
            score = 0.0
            reasons: list[str] = []

            if required_capability in capabilities or required_capability in skill_name:
                score += 100
                reasons.append("capability_match")
            elif required_capability.split(".")[0] in skill_name:
                score += 30
                reasons.append("name_partial_match")

            if required_tools <= tool_names:
                score += 20
                reasons.append("tools_available")
            else:
                score -= 50
                reasons.append("missing_tools")

            skill_history = history.get(skill_name, {})
            score += float(skill_history.get("success_rate", 0.5)) * 20
            score -= float(metadata.get("cost", 1.0))
            score -= float(metadata.get("avg_duration_ms", 1000)) / 10000

            if score > 0:
                ranked.append(SkillCandidate(skill_name, score, reasons))
        return sorted(ranked, key=lambda item: item.score, reverse=True)


class PlannerEngine:
    name = "planner.engine"

    def __init__(self, skill_selector: SkillSelector | None = None) -> None:
        self.skill_selector = skill_selector or SkillSelector()

    def plan(
        self,
        task: Task,
        context: ExecutionContext,
        available_skills: SkillRegistry,
        available_tools: ToolRegistry,
        available_agents: AgentRegistry,
    ) -> ExecutionPlan:
        started = time.monotonic()
        context.emit(Event(EventType.PLANNING_STARTED, task.id, {"planner": self.name}))
        capabilities = self._capabilities_for(task)
        steps: list[ExecutionStep] = []
        previous_id: str | None = None

        for capability in capabilities:
            skill = self.skill_selector.select(capability, available_skills, available_tools, context)
            adapter = available_agents.find_adapter_for_capability(capability)
            tools = self._tools_for_capability(capability, available_tools.names())
            step = ExecutionStep(
                id=self._stable_step_id(capability),
                description=self._description_for(capability),
                required_skill=skill.name,
                required_capability=capability,
                required_tools=tools,
                dependencies=[previous_id] if previous_id else [],
                success_criteria=self._success_criteria_for(capability, task),
                retry_policy=RetryPolicy(max_attempts=task.max_attempts),
                timeout=context.configuration.workflow_timeout_seconds,
                expected_artifacts=self._expected_artifacts_for(capability),
                metadata={
                    "skill_score": skill.score,
                    "skill_reasons": skill.reasons,
                    "adapter": getattr(adapter, "name", None),
                    "capability": capability,
                },
            )
            steps.append(step)
            previous_id = step.id

        plan = ExecutionPlan(task_id=task.id, steps=steps, metadata={"agents": available_agents.names()})
        metrics = plan.metrics()
        metrics["planning_time_ms"] = (time.monotonic() - started) * 1000
        for name, value in metrics.items():
            context.metrics.set(f"planning.{name}", value)
        context.runtime_variables["execution_plan"] = plan
        context.add_artifact(PlanArtifact(self.name, plan.to_dict(), revision=plan.revision))
        context.emit(Event(EventType.PLANNING_COMPLETED, task.id, {"plan_id": plan.id, **metrics}))
        return plan

    def replan_failed_subtree(
        self,
        plan: ExecutionPlan,
        failed_step_id: str,
        context: ExecutionContext,
    ) -> ExecutionPlan:
        replanned = plan.subtree(failed_step_id)
        context.runtime_variables["execution_plan"] = replanned
        context.metrics.increment("plan_revisions")
        context.add_artifact(PlanArtifact(self.name, replanned.to_dict(), revision=replanned.revision, subtree_root=failed_step_id))
        context.emit(
            Event(
                EventType.PLAN_REVISED,
                context.task.id,
                {"plan_id": replanned.id, "revision": replanned.revision, "failed_step_id": failed_step_id},
            )
        )
        return replanned

    def plan_workflow_definition(
        self,
        workflow_definition: Any,
        task: Task,
        context: ExecutionContext,
        parameters: dict[str, Any] | None = None,
        registry: Any | None = None,
    ) -> ExecutionPlan:
        started = time.monotonic()
        context.emit(Event(EventType.PLANNING_STARTED, task.id, {"planner": self.name, "workflow": workflow_definition.name}))
        plan = workflow_definition.to_execution_plan(task, parameters=parameters, registry=registry)
        metrics = plan.metrics()
        metrics["planning_time_ms"] = (time.monotonic() - started) * 1000
        for name, value in metrics.items():
            context.metrics.set(f"planning.{name}", value)
        context.runtime_variables["execution_plan"] = plan
        context.add_artifact(PlanArtifact(self.name, plan.to_dict(), workflow=workflow_definition.name, revision=plan.revision))
        context.emit(Event(EventType.PLANNING_COMPLETED, task.id, {"plan_id": plan.id, "workflow": workflow_definition.name, **metrics}))
        return plan

    def _capabilities_for(self, task: Task) -> list[str]:
        explicit = task.metadata.get("capabilities")
        if isinstance(explicit, list) and explicit:
            return [str(item) for item in explicit]

        text = f"{task.title} {task.description} {task.goal}".lower()
        capabilities = ["planning"]
        if "research" in text:
            capabilities.append("research")
        if "architecture" in text or "design" in text:
            capabilities.append("architecture")
        if any(word in text for word in ["build", "implement", "feature", "code", "fix", "debug"]):
            capabilities.append("coding")
        if any(word in text for word in ["test", "verify", "bug", "debug"]):
            capabilities.append("testing")
        if "review" in text:
            capabilities.append("review")
        if "document" in text or "docs" in text:
            capabilities.append("documentation")
        if capabilities == ["planning"]:
            capabilities.extend(["coding", "testing"])
        return capabilities

    def _stable_step_id(self, capability: str) -> str:
        return f"step_{capability.replace('.', '_')}"

    def _description_for(self, capability: str) -> str:
        return f"Execute {capability} work"

    def _success_criteria_for(self, capability: str, task: Task) -> list[str]:
        if capability in {"testing", "verification"}:
            return ["configured verification passes"]
        if capability == "planning":
            return ["execution plan is available"]
        return task.acceptance_criteria or [f"{capability} step completed"]

    def _expected_artifacts_for(self, capability: str) -> list[str]:
        mapping = {
            "planning": ["plan"],
            "coding": ["implementation"],
            "testing": ["test"],
            "verification": ["verification"],
            "documentation": ["documentation"],
            "review": ["review"],
            "architecture": ["documentation"],
            "research": ["documentation"],
        }
        return mapping.get(capability, ["log"])

    def _tools_for_capability(self, capability: str, tool_names: Iterable[str]) -> list[str]:
        available = set(tool_names)
        preferred = {
            "coding": ["filesystem", "shell"],
            "testing": ["test", "shell"],
            "verification": ["test", "shell"],
            "documentation": ["filesystem"],
            "research": ["search"],
            "review": ["git"],
            "architecture": ["filesystem"],
        }.get(capability, [])
        return [tool for tool in preferred if tool in available]
