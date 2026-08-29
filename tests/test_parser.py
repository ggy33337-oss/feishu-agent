import asyncio

from app.core.parser.schemas import StructuredTask, TaskExtraction, TaskType
from app.core.parser.task_parser import TaskParser
from app.models.llm import LLMClient


class StubLLM:
    async def extract_task(self, text: str) -> TaskExtraction:
        return TaskExtraction(
            task_type=TaskType.PPT,
            user_intent="Create a presentation",
            normalized_text=text.strip(),
            entities=["Q3"],
            constraints=["short"],
        )


def test_parse_feishu_text_message_uses_llm() -> None:
    payload = {
        "event": {
            "sender": {"sender_id": {"open_id": "ou_test"}, "sender_type": "user"},
            "message": {
                "chat_id": "oc_test",
                "content": "帮我做一个 PPT 汇报",
            },
        }
    }

    task = asyncio.run(TaskParser(StubLLM()).parse(payload))

    assert isinstance(task, StructuredTask)
    assert task.task_type == TaskType.PPT
    assert task.user_id == "ou_test"
    assert task.chat_id == "oc_test"
    assert task.user_intent == "Create a presentation"


def test_qwen_payload_normalization_coerces_object_lists() -> None:
    client = LLMClient.__new__(LLMClient)
    payload = {
        "task_type": "excel",
        "user_intent": "Generate spreadsheet",
        "normalized_text": "Generate spreadsheet",
        "entities": {},
        "constraints": {},
    }

    normalized = client._normalize_payload(payload, TaskExtraction)

    assert normalized["entities"] == []
    assert normalized["constraints"] == []


def test_parse_ignores_non_user_messages() -> None:
    payload = {
        "event": {
            "sender": {"sender_type": "bot"},
            "message": {"content": "hello"},
        }
    }

    try:
        asyncio.run(TaskParser(StubLLM()).parse(payload))
    except ValueError as exc:
        assert "Ignored non-user message" in str(exc)
    else:
        raise AssertionError("Expected non-user messages to be ignored")
