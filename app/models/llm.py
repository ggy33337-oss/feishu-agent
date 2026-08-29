import asyncio
import json
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.core.parser.schemas import RouteDecision, StructuredTask, TaskExtraction
from config.settings import settings


class LLMClient:
    """Qwen/DashScope-backed structured output client."""

    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
        )

    async def complete(self, prompt: str, **kwargs: Any) -> str:
        raise NotImplementedError("Use structured task and skill selection methods.")

    async def extract_task(self, text: str) -> TaskExtraction:
        return await asyncio.to_thread(self._extract_task_sync, text)

    async def select_skill(
        self,
        task: StructuredTask,
        available_skills: list[str],
    ) -> RouteDecision:
        return await asyncio.to_thread(self._select_skill_sync, task, available_skills)

    def _extract_task_sync(self, text: str) -> TaskExtraction:
        completion = self.client.chat.completions.create(
            model=settings.qwen_task_parser_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract a structured task from a Feishu message. "
                        "Return only a JSON object with these fields: "
                        "task_type, user_intent, normalized_text, entities, constraints. "
                        "task_type must be one of: excel, ppt, copywriter, image, search, general. "
                        "entities and constraints must be JSON arrays, not objects."
                    ),
                },
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"},
        )
        return self._parse_json_response(completion.choices[0].message.content, TaskExtraction)

    def _select_skill_sync(
        self,
        task: StructuredTask,
        available_skills: list[str],
    ) -> RouteDecision:
        completion = self.client.chat.completions.create(
            model=settings.qwen_agent_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Decide whether to answer directly or use a tool. "
                        "Return only a JSON object with these fields: mode, skill_name, answer, rationale, confidence, parameters. "
                        "mode must be either direct or tool. "
                        "Prefer direct mode for arithmetic, general knowledge, greetings, and conversational questions. "
                        "Only choose tool mode when external data, files, specialized generation, or a skill is clearly needed. "
                        "For the feishu_lark_agent skill, parameters must include category, action, and flags matching the vendored CLI, such as "
                        "{\"category\":\"msg\",\"action\":\"send\",\"flags\":{\"to\":\"oc_xxx\",\"text\":\"hello\"}}. "
                        "If mode is tool, skill_name must exactly match one item from the provided skill list and answer must be null. "
                        "parameters must contain the structured arguments needed by the selected skill. "
                        "If mode is direct, answer must contain the final user-facing reply in Chinese and skill_name must be null. "
                        "confidence must be a number from 0 to 1."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Task type: {task.task_type.value}\n"
                        f"Intent: {task.user_intent}\n"
                        f"Text: {task.normalized_text}\n"
                        f"Available skills: {', '.join(available_skills)}"
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
        return self._parse_json_response(completion.choices[0].message.content, RouteDecision)

    def _parse_json_response(self, content: str | None, schema: type[BaseModel]) -> Any:
        if not content:
            raise RuntimeError("Qwen returned an empty response.")
        try:
            payload = json.loads(content)
            payload = self._normalize_payload(payload, schema)
            return schema.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError(f"Qwen returned invalid structured data: {content}") from exc

    def _normalize_payload(self, payload: Any, schema: type[BaseModel]) -> Any:
        if schema is TaskExtraction and isinstance(payload, dict):
            for key in ("entities", "constraints"):
                value = payload.get(key)
                if value is None:
                    payload[key] = []
                elif isinstance(value, dict):
                    payload[key] = list(value.values()) if value else []
                elif not isinstance(value, list):
                    payload[key] = [value]
        if schema is RouteDecision and isinstance(payload, dict):
            if payload.get("mode") == "direct":
                payload["skill_name"] = None
                payload["parameters"] = {}
            elif payload.get("mode") == "tool":
                payload["answer"] = None
            if not isinstance(payload.get("parameters"), dict):
                payload["parameters"] = {}
        return payload
