from typing import Any

from app.core.parser.schemas import SkillResult
from app.skills.base import Skill
from app.skills.excel.executor import ExcelExecutor


class ExcelSkill(Skill):
    name = "excel"
    description = "Handle spreadsheet analysis and generation tasks."

    def __init__(self, executor: ExcelExecutor | None = None) -> None:
        self.executor = executor or ExcelExecutor()

    async def run(self, inputs: dict[str, Any]) -> SkillResult:
        data = await self.executor.execute(inputs)
        return SkillResult(ok=True, message="已收到表格任务，正在准备处理。", data=data)

