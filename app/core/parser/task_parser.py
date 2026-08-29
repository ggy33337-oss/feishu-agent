import json
from typing import Any

from app.core.parser.schemas import StructuredTask
from app.models.llm import LLMClient


class TaskParser:
    """Convert Feishu webhook payloads into structured tasks using an LLM."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    async def parse(self, payload: dict[str, Any]) -> StructuredTask:
        event = payload.get("event", payload)
        message = event.get("message", {})
        sender = event.get("sender", {})
        sender_type = sender.get("sender_type") if isinstance(sender, dict) else None
        if sender_type and sender_type != "user":
            raise ValueError("Ignored non-user message.")

        text = self._extract_text(message)
        if not text:
            raise ValueError("No message text found in Feishu payload.")

        extracted = await self.llm.extract_task(text)
        return StructuredTask(
            task_type=extracted.task_type,
            user_intent=extracted.user_intent,
            normalized_text=extracted.normalized_text,
            user_id=self._nested_get(sender, "sender_id", "open_id"),
            chat_id=message.get("chat_id"),
            message_id=message.get("message_id"),
            reply_token=event.get("reply_token"),
            attachments=message.get("attachments", []),
            entities=extracted.entities,
            constraints=extracted.constraints,
            raw=payload,
        )

    def _extract_text(self, message: dict[str, Any]) -> str:
        content = message.get("content")
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                return content.strip()
            if isinstance(parsed, dict):
                return str(parsed.get("text", "")).strip()
            return str(parsed).strip()
        if isinstance(content, dict):
            return str(content.get("text", "")).strip()
        return str(message.get("text", "")).strip()

    def _nested_get(self, data: dict[str, Any], *keys: str) -> Any:
        current: Any = data
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current
