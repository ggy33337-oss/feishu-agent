# -*- coding: utf-8 -*-
from typing import Any


class ImageExecutor:
    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            "prompt": inputs.get("text", ""),
            "status": "queued",
        }
