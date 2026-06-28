from __future__ import annotations

from core.artifacts import CodeArtifact
from core.execution import ExecutionContext
from skills.base import Skill, SkillResult


class CodingSkill(Skill):
    name = "coding.default"
    metadata = {"capabilities": ["coding", "implementation"], "tools": [], "cost": 2.0, "avg_duration_ms": 500}

    def run(self, context: ExecutionContext) -> SkillResult:
        task = context.task
        plan = context.artifact_store.latest_content("plan", {})
        feedback_summaries = [
            getattr(item, "summary", str(item))
            for item in context.feedback
        ]
        revision = 1 + len(feedback_summaries)
        implementation = {
            "task_id": task.id,
            "revision": revision,
            "plan_steps": list(plan.get("steps", [])),
            "acceptance_criteria": list(task.acceptance_criteria),
            "feedback_addressed": feedback_summaries,
            "notes": (
                "Phase 1 coding skill produces structured implementation artifacts. "
                "Repository-editing skills can replace it without scheduler changes."
            ),
        }
        return SkillResult(
            success=True,
            output={"implementation": implementation},
            artifacts=[CodeArtifact(self.name, implementation)],
            logs=[f"produced implementation revision {revision}"],
            metrics={"implementation_revision": revision},
        )

    def validate(self, context: ExecutionContext, result: SkillResult) -> SkillResult:
        implementation = result.output.get("implementation")
        if not result.success or not isinstance(implementation, dict):
            return SkillResult(
                success=False,
                output=result.output,
                artifacts=result.artifacts,
                logs=result.logs,
                errors=[*result.errors, "coding skill did not produce an implementation artifact"],
                metrics=result.metrics,
            )
        if not implementation.get("plan_steps"):
            return SkillResult(
                success=False,
                output=result.output,
                artifacts=result.artifacts,
                logs=result.logs,
                errors=[*result.errors, "coding skill ran without a plan"],
                metrics=result.metrics,
            )
        return result
