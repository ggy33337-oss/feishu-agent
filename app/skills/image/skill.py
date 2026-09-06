# -*- coding: utf-8 -*-
from app.domain.contracts import SkillContext, SkillResult
from app.skills.base import Skill
from app.skills.image.executor import ImageExecutor


class ImageSkill(Skill):
    name = "image"
    description = "Handle image and poster generation tasks."

    def __init__(self, executor: ImageExecutor | None = None) -> None:
        self.executor = executor or ImageExecutor()

    async def run(self, inputs: SkillContext | dict[str, object]) -> SkillResult:
        context = self.context(inputs)
        data = await self.executor.execute(context.to_executor_input())
        return SkillResult(ok=True, message="已收到图片任务，生成流程已排队。", data=data)
