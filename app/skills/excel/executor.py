from typing import Any


class ExcelExecutor:
    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            "summary": "Excel task accepted",
            "requested_text": inputs.get("text", ""),
        }

