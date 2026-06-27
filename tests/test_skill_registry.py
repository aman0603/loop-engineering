from core.task_manager import Task
from skills import Skill, SkillContext, SkillRegistry, SkillResult


class ExampleSkill(Skill):
    name = "example"

    def run(self, task: Task, context: SkillContext) -> SkillResult:
        return SkillResult(success=True, output={"ok": True})


def test_skill_registry_registers_and_retrieves_skills():
    registry = SkillRegistry()
    skill = ExampleSkill()

    registry.register(skill)

    assert registry.get("example") is skill
    assert registry.list() == [skill]

