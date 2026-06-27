from __future__ import annotations

from core.artifacts import PlanArtifact
from core.execution import ExecutionContext
from skills.base import Skill, SkillResult


class PlanningSkill(Skill):
    name = "planning.default"

    def run(self, context: ExecutionContext) -> SkillResult:
        task = context.task
        feedback_summaries = [
            getattr(item, "summary", str(item))
            for item in context.feedback
        ]
        steps = [
            "Understand task goal and acceptance criteria",
            "Design the smallest implementation that satisfies the criteria",
            "Implement changes in an isolated workspace",
            "Run configured verification checks",
        ]
        if feedback_summaries:
            steps.insert(1, "Address verification feedback from the previous attempt")

        plan = {
            "task_id": task.id,
            "goal": task.goal,
            "acceptance_criteria": list(task.acceptance_criteria),
            "steps": steps,
            "feedback_considered": feedback_summaries,
        }
        return SkillResult(
            success=True,
            output={"plan": plan},
            artifacts=[PlanArtifact(self.name, plan)],
            logs=[f"created plan with {len(steps)} steps"],
            metrics={"planned_steps": len(steps)},
        )

    def validate(self, context: ExecutionContext, result: SkillResult) -> SkillResult:
        plan = result.output.get("plan")
        if not result.success or not isinstance(plan, dict) or not plan.get("steps"):
            return SkillResult(
                success=False,
                output=result.output,
                artifacts=result.artifacts,
                logs=result.logs,
                errors=[*result.errors, "planning skill did not produce a usable plan"],
                metrics=result.metrics,
            )
        return result
