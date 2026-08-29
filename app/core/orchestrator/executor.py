from app.core.parser.schemas import Plan, SkillResult
from app.skills.registry import SkillRegistry


class Executor:
    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self.registry = registry or SkillRegistry.default()

    async def execute(self, plan: Plan) -> SkillResult:
        skill = self.registry.get(plan.skill_name)
        return await skill.run(plan.inputs)

