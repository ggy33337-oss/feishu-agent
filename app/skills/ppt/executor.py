# -*- coding: utf-8 -*-
from typing import Any


class PptExecutor:
    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            "outline": ["封面", "核心观点", "数据支撑", "结论"],
            "requested_text": inputs.get("text", ""),
        }
