from agents.base import SkillAgent
from skills.coding import CodingSkill


class CodingAgent(SkillAgent):
    def __init__(self, skill: CodingSkill | None = None) -> None:
        super().__init__("coder", skill or CodingSkill())

