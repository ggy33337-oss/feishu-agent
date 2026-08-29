from typing import Any


class SearchExecutor:
    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            "query": inputs.get("text", ""),
            "results": [],
        }

