# -*- coding: utf-8 -*-
import asyncio
import json
from types import SimpleNamespace

import pytest

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


class FailingLLM:
    async def extract_task(self, text: str) -> TaskExtraction:
        raise RuntimeError("invalid structured task")


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
    assert task.source_text == "帮我做一个 PPT 汇报"


def test_parse_feishu_file_message_extracts_attachment() -> None:
    payload = {
        "event": {
            "sender": {"sender_id": {"open_id": "ou_test"}, "sender_type": "user"},
            "message": {
                "message_id": "om_test",
                "chat_id": "oc_test",
                "message_type": "file",
                "content": '{"file_key":"file_test","file_name":"销售数据.xlsx"}',
            },
        }
    }

    task = asyncio.run(TaskParser(StubLLM()).parse(payload))

    assert task.normalized_text == "请处理 Excel 文件：销售数据.xlsx"
    assert task.attachments == [
        {
            "type": "file",
            "file_key": "file_test",
            "name": "销售数据.xlsx",
        }
    ]


def test_parse_feishu_post_message_extracts_multiline_rich_text() -> None:
    payload = {
        "event": {
            "sender": {"sender_id": {"open_id": "ou_test"}, "sender_type": "user"},
            "message": {
                "message_type": "post",
                "content": (
                    '{"zh_cn":{"title":"","content":['
                    '[{"tag":"text","text":"工号,姓名,部门"}],'
                    '[{"tag":"text","text":"EMP001,张伟,技术部"}]]'
                    '}}'
                ),
            },
        }
    }

    task = asyncio.run(TaskParser(StubLLM()).parse(payload))

    assert task.normalized_text == "工号,姓名,部门\nEMP001,张伟,技术部"


def test_qwen_payload_normalization_coerces_object_lists() -> None:
    client = LLMClient.__new__(LLMClient)
    payload = {
        "task_type": "search",
        "user_intent": "Find technology news",
        "normalized_text": "今天的10条科技新闻",
        "entities": [
            {"type": "date", "value": "2026-08-30", "span": "今天"},
            {"type": "topic", "value": "科技新闻", "span": "科技新闻"},
        ],
        "constraints": {"time": "今天", "count": "10条"},
        "subtasks": [
            {
                "order": 1,
                "goal": "搜索科技新闻",
                "task_type": "search",
                "normalized_text": "今天的10条科技新闻",
                "hints": "优先最新结果",
            }
        ],
    }

    normalized = client._normalize_payload(payload, TaskExtraction)

    assert normalized["entities"] == ["2026-08-30", "科技新闻"]
    assert normalized["constraints"] == ["今天", "10条"]
    assert normalized["subtasks"][0]["hints"] == ["优先最新结果"]
    assert normalized["subtasks"][0]["dependencies"] == []


def test_task_extraction_retries_invalid_model_schema() -> None:
    invalid = json.dumps({"execution_mode": "workflow"}, ensure_ascii=False)
    valid = json.dumps(
        {
            "execution_mode": "workflow",
            "task_type": "search",
            "user_intent": "搜索科技新闻",
            "normalized_text": "今天的10条科技新闻",
            "entities": [],
            "constraints": [],
            "subtasks": [],
        },
        ensure_ascii=False,
    )

    class FakeCompletions:
        def __init__(self) -> None:
            self.outputs = [invalid, valid]
            self.calls = 0

        def create(self, **kwargs):  # type: ignore[no-untyped-def]
            content = self.outputs[self.calls]
            self.calls += 1
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    completions = FakeCompletions()
    client = LLMClient.__new__(LLMClient)
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    extracted = client._extract_task_sync("今天的10条科技新闻")

    assert extracted.task_type == TaskType.SEARCH
    assert completions.calls == 2


def test_chinese_search_summary_retries_untranslated_response() -> None:
    untranslated = json.dumps(
        {"items": [{"title": "AI news", "summary": "An English summary."}]},
        ensure_ascii=False,
    )
    translated = json.dumps(
        {"items": [{"title": "人工智能新闻", "summary": "这是一条经过概括的中文新闻摘要。"}]},
        ensure_ascii=False,
    )

    class FakeCompletions:
        def __init__(self) -> None:
            self.outputs = [untranslated, translated]
            self.calls = 0

        def create(self, **kwargs):  # type: ignore[no-untyped-def]
            content = self.outputs[self.calls]
            self.calls += 1
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    completions = FakeCompletions()
    client = LLMClient.__new__(LLMClient)
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = client._translate_search_batch_sync(
        [{"title": "AI news", "summary": "An English summary."}]
    )

    assert result == [
        {"title": "人工智能新闻", "summary": "这是一条经过概括的中文新闻摘要。"}
    ]
    assert completions.calls == 2


def test_chinese_search_summary_accepts_direct_json_array() -> None:
    translated = json.dumps(
        [{"title": "人工智能新闻", "summary": "这是一条中文新闻摘要。"}],
        ensure_ascii=False,
    )

    class FakeCompletions:
        def create(self, **kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=translated))]
            )

    client = LLMClient.__new__(LLMClient)
    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )

    result = client._translate_search_batch_sync(
        [{"title": "AI news", "summary": "An English summary."}]
    )

    assert result == [
        {"title": "人工智能新闻", "summary": "这是一条中文新闻摘要。"}
    ]


def test_parse_falls_back_to_original_text_for_clear_search_request() -> None:
    payload = {
        "event": {
            "sender": {"sender_id": {"open_id": "ou_test"}, "sender_type": "user"},
            "message": {
                "chat_id": "oc_test",
                "content": "@_user_1 今天的10条科技新闻",
            },
        }
    }

    task = asyncio.run(TaskParser(FailingLLM()).parse(payload))

    assert task.task_type == TaskType.SEARCH
    assert task.normalized_text == "今天的10条科技新闻"
    assert task.constraints == ["数量：10条", "时间：今天"]
    assert len(task.subtasks) == 1


def test_parse_does_not_guess_non_search_task_after_model_failure() -> None:
    payload = {
        "event": {
            "sender": {"sender_type": "user"},
            "message": {"content": "帮我分析一下"},
        }
    }

    with pytest.raises(RuntimeError, match="invalid structured task"):
        asyncio.run(TaskParser(FailingLLM()).parse(payload))


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


def test_parse_lets_intent_router_choose_excel_creation() -> None:
    class RouterStub:
        def __init__(self) -> None:
            self.calls = 0
            self.analyze_calls = 0

        async def route_task(self, text: str, attachments: list[dict[str, object]], catalog: list[dict[str, str]]):
            self.calls += 1
            from app.domain.contracts import RouteDecision

            return RouteDecision(
                mode="tool",
                skill_name="excel",
                skill_reason="用户请求生成 Excel",
                parameters={"operation": "create", "workbook_spec": {"sheets": [{"rows": 5}]}},
            )

        async def analyze_tool_input(
            self,
            text: str,
            skill_name: str,
            attachments: list[dict[str, object]],
        ) -> dict[str, object]:
            self.analyze_calls += 1
            return {
                "operation": "create",
                "filename": "模型提炼.xlsx",
                "workbook_spec": {"sheets": [{"name": "数据", "rows": [["姓名", "部门"]], "cells": {}}]},
            }

    payload = {
        "event": {
            "sender": {"sender_type": "user"},
            "message": {"message_id": "om_excel", "content": "生成excel表"},
        }
    }

    router = RouterStub()
    task = asyncio.run(TaskParser(router, skill_catalog=[{"name": "excel", "description": "xlsx"}]).parse(payload))

    assert router.calls == 1
    assert router.analyze_calls == 1
    assert task.route_skill == "excel"
    assert task.route_parameters["filename"] == "模型提炼.xlsx"
    assert task.route_parameters["workbook_spec"]["sheets"][0]["rows"] == [["姓名", "部门"]]


def test_parse_search_route_normalizes_three_layer_query_plan() -> None:
    class SearchRouterStub:
        async def route_task(
            self,
            text: str,
            attachments: list[dict[str, object]],
            catalog: list[dict[str, str]],
        ):
            from app.domain.contracts import RouteDecision

            return RouteDecision(
                mode="tool",
                skill_name="search",
                skill_reason="用户请求搜索信息",
                parameters={"query": text},
                requires_summary=True,
            )

        async def analyze_tool_input(
            self,
            text: str,
            skill_name: str,
            attachments: list[dict[str, object]],
        ) -> dict[str, object]:
            return {
                "query": "请搜索今天10条科技新闻",
                "planned_queries": [
                    {"level": 1, "purpose": "核心", "query": "请搜索今天10条科技新闻"},
                    {"query": "请搜索今天10条科技新闻"},
                ],
            }

    payload = {
        "event": {
            "sender": {"sender_type": "user"},
            "message": {"content": "请搜索今天10条科技新闻"},
        }
    }
    task = asyncio.run(
        TaskParser(SearchRouterStub(), skill_catalog=[{"name": "search", "description": "web search"}]).parse(
            payload
        )
    )

    planned = task.route_parameters["planned_queries"]
    assert isinstance(planned, list)
    assert len(planned) == 3
    assert [item["level"] for item in planned] == [1, 2, 3]
    assert len({item["query"] for item in planned}) == 3
    assert task.route_parameters["query"] == planned[0]["query"]
    assert all("请搜索" not in item["query"] for item in planned)


def test_inline_csv_is_normalized_to_excel_create_without_attachment() -> None:
    source = "name,department\n陈宇恒,研发部\n生成excel表"
    normalized = TaskParser._normalize_excel_parameters(
        {"operation": "csv_to_xlsx"},
        source,
    )

    assert normalized["operation"] == "create"
    assert normalized["workbook_spec"]["sheets"][0]["rows"] == [
        ["name", "department"],
        ["陈宇恒", "研发部"],
    ]
