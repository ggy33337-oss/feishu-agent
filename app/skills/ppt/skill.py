# -*- coding: utf-8 -*-
from app.domain.contracts import SkillContext, SkillResult
from app.skills.base import Skill
from app.skills.ppt.executor import PptExecutor


class PptSkill(Skill):
    name = "ppt"
    description = "Handle presentation planning and generation tasks."

    def __init__(self, executor: PptExecutor | None = None) -> None:
        self.executor = executor or PptExecutor()

    async def run(self, inputs: SkillContext | dict[str, object]) -> SkillResult:
        context = self.context(inputs)
        data = await self.executor.execute(context.to_executor_input())
        return SkillResult(ok=True, message="已收到 PPT 任务，先为你生成了基础大纲。", data=data)
