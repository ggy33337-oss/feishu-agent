from typing import Any


class CopywriterExecutor:
    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        text = inputs.get("text", "")
        return {
            "draft": f"收到需求：{text}",
            "style": "concise",
        }

