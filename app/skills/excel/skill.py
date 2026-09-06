# -*- coding: utf-8 -*-
from app.domain.contracts import SkillContext, SkillResult
from app.skills.base import Skill
from app.skills.excel.executor import ExcelExecutor


class ExcelSkill(Skill):
    name = "excel"
    description = (
        "Create, inspect, edit, and convert real Excel .xlsx and UTF-8 CSV files with "
        "formulas, professional formatting, tables, charts, validation, and output verification."
    )

    def __init__(self, executor: ExcelExecutor | None = None) -> None:
        self.executor = executor or ExcelExecutor()

    async def run(self, inputs: SkillContext | dict[str, object]) -> SkillResult:
        context = self.context(inputs)
        data = await self.executor.execute(context.to_executor_input())
        artifacts: list[dict[str, object]] = []
        if data.get("output_path"):
            artifacts.append(
                {
                    "type": "file",
                    "path": data["output_path"],
                    "name": data.get("output_name"),
                    "mime_type": data.get("mime_type"),
                }
            )
        operation = data.get("operation", "excel")
        return SkillResult(
            ok=True,
            message=f"Excel {operation} 操作已完成并通过文件检查。",
            artifacts=artifacts,
            data=data,
        )
