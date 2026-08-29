from typing import Any

from app.core.parser.schemas import SkillResult
from app.skills.base import Skill
from app.skills.ppt.executor import PptExecutor


class PptSkill(Skill):
    name = "ppt"
    description = "Handle presentation planning and generation tasks."

    def __init__(self, executor: PptExecutor | None = None) -> None:
        self.executor = executor or PptExecutor()

    async def run(self, inputs: dict[str, Any]) -> SkillResult:
        data = await self.executor.execute(inputs)
        return SkillResult(ok=True, message="已收到 PPT 任务，先为你生成了基础大纲。", data=data)

