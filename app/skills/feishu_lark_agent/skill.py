from typing import Any

from app.core.parser.schemas import SkillResult
from app.skills.base import Skill
from app.skills.feishu_lark_agent.executor import FeishuLarkAgentExecutor


class FeishuLarkAgentSkill(Skill):
    name = "feishu_lark_agent"
    description = "Run Feishu/Lark API operations through the vendored CLI."

    def __init__(self, executor: FeishuLarkAgentExecutor | None = None) -> None:
        self.executor = executor or FeishuLarkAgentExecutor()

    async def run(self, inputs: dict[str, Any]) -> SkillResult:
        data = await self.executor.execute(inputs)
        return SkillResult(ok=True, message=self._format_message(data), data=data)

    def _format_message(self, data: dict[str, Any]) -> str:
        if isinstance(data, dict):
            if data.get("url"):
                return f"飞书/Lark 操作已执行：{data['url']}"
            if data.get("message_id"):
                return f"飞书/Lark 操作已执行，message_id={data['message_id']}"
            if data.get("record_id"):
                return f"飞书/Lark 操作已执行，record_id={data['record_id']}"
            if data.get("task_id"):
                return f"飞书/Lark 操作已执行，task_id={data['task_id']}"
            if data.get("image_key"):
                return f"飞书/Lark 操作已执行，image_key={data['image_key']}"
        return "飞书/Lark 操作已执行。"
