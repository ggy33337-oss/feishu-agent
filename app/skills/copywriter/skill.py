from typing import Any

from app.core.parser.schemas import SkillResult
from app.skills.base import Skill
from app.skills.copywriter.executor import CopywriterExecutor


class CopywriterSkill(Skill):
    name = "copywriter"
    description = "Handle writing, editing, and rewriting tasks."

    def __init__(self, executor: CopywriterExecutor | None = None) -> None:
        self.executor = executor or CopywriterExecutor()

    async def run(self, inputs: dict[str, Any]) -> SkillResult:
        data = await self.executor.execute(inputs)
        return SkillResult(ok=True, message="已收到文案任务，这是一个初稿占位结果。", data=data)

