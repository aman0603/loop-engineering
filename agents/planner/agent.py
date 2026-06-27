from agents.base import SkillAgent
from skills.planning import PlanningSkill


class PlannerAgent(SkillAgent):
    def __init__(self, skill: PlanningSkill | None = None) -> None:
        super().__init__("planner", skill or PlanningSkill())

