from app.skills.base import Skill
from app.skills.copywriter.skill import CopywriterSkill
from app.skills.feishu_lark_agent.skill import FeishuLarkAgentSkill
from app.skills.excel.skill import ExcelSkill
from app.skills.image.skill import ImageSkill
from app.skills.ppt.skill import PptSkill
from app.skills.search.skill import SearchSkill


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill:
        try:
            return self._skills[name]
        except KeyError as exc:
            available = ", ".join(sorted(self._skills))
            raise ValueError(f"Skill '{name}' not found. Available: {available}") from exc

    def available_names(self) -> list[str]:
        return sorted(self._skills)

    @classmethod
    def default(cls) -> "SkillRegistry":
        registry = cls()
        for skill in (
            ExcelSkill(),
            PptSkill(),
            CopywriterSkill(),
            ImageSkill(),
            SearchSkill(),
            FeishuLarkAgentSkill(),
        ):
            registry.register(skill)
        return registry
