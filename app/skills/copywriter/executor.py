# -*- coding: utf-8 -*-
from typing import Any


class CopywriterExecutor:
    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        text = inputs.get("text", "")
        previous_outputs = inputs.get("previous_outputs") if isinstance(inputs.get("previous_outputs"), list) else []
        source_summary = ""
        if previous_outputs:
            last_output = previous_outputs[-1]
            if isinstance(last_output, dict):
                source_summary = str(last_output.get("message", ""))
        return {
            "draft": f"Draft based on prior output: {source_summary or text}",
            "style": "concise",
            "source_summary": source_summary,
        }
