from typing import Any

from app.core.parser.schemas import SkillResult
from app.skills.base import Skill
from app.skills.image.executor import ImageExecutor


class ImageSkill(Skill):
    name = "image"
    description = "Handle image and poster generation tasks."

    def __init__(self, executor: ImageExecutor | None = None) -> None:
        self.executor = executor or ImageExecutor()

    async def run(self, inputs: dict[str, Any]) -> SkillResult:
        data = await self.executor.execute(inputs)
        return SkillResult(ok=True, message="已收到图片任务，生成流程已排队。", data=data)

