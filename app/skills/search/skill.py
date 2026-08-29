from typing import Any

from app.core.parser.schemas import SkillResult
from app.skills.base import Skill
from app.skills.search.executor import SearchExecutor


class SearchSkill(Skill):
    name = "search"
    description = "Handle search and research tasks."

    def __init__(self, executor: SearchExecutor | None = None) -> None:
        self.executor = executor or SearchExecutor()

    async def run(self, inputs: dict[str, Any]) -> SkillResult:
        data = await self.executor.execute(inputs)
        return SkillResult(ok=True, message="已收到检索任务，后续可接入搜索 API。", data=data)

