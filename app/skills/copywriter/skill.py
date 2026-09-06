# -*- coding: utf-8 -*-
from app.domain.contracts import SkillContext, SkillResult
from app.skills.base import Skill
from app.skills.copywriter.executor import CopywriterExecutor


class CopywriterSkill(Skill):
    name = "copywriter"
    description = "Handle writing, editing, and rewriting tasks."

    def __init__(self, executor: CopywriterExecutor | None = None) -> None:
        self.executor = executor or CopywriterExecutor()

    async def run(self, inputs: SkillContext | dict[str, object]) -> SkillResult:
        context = self.context(inputs)
        data = await self.executor.execute(context.to_executor_input())
        return SkillResult(ok=True, message="已收到文案任务，这是一个初稿占位结果。", data=data)
