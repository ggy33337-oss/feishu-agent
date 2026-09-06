# -*- coding: utf-8 -*-
import asyncio

import pytest

from app.core.orchestrator.agent import Agent
from app.core.parser.schemas import (
    ResearchAction,
    SkillResult,
    StructuredTask,
    TaskType,
    WorkflowAssessment,
    WorkflowPlan,
    WorkflowStep,
)
from app.models.llm import LLMClient


class DirectStubLLM:
    async def plan_workflow(self, task: StructuredTask, skill_catalog: list[dict[str, str]]) -> WorkflowPlan:
        return WorkflowPlan(
            mode="direct",
            answer="I cannot check weather right now, but I can help you search for it.",
            rationale="No external tool required",
            confidence=0.91,
        )


class WorkflowStubLLM:
    async def plan_workflow(self, task: StructuredTask, skill_catalog: list[dict[str, str]]) -> WorkflowPlan:
        return WorkflowPlan(
            mode="workflow",
            rationale="Need a draft first, then a presentation outline",
            confidence=0.98,
            subtasks=task.subtasks or [],
            steps=[
                WorkflowStep(
                    order=1,
                    subtask_id="subtask-write",
                    skill_name="copywriter",
                    skill_reason="Need a concise draft",
                    goal="Write a concise draft",
                    inputs={"style": "concise"},
                ),
                WorkflowStep(
                    order=2,
                    subtask_id="subtask-slides",
                    skill_name="ppt",
                    skill_reason="Need a presentation outline",
                    goal="Turn the draft into a presentation outline",
                ),
            ],
        )

    async def summarize_workflow_result(
        self,
        task: StructuredTask,
        workflow: WorkflowPlan,
        step_results: list[dict[str, object]],
    ) -> WorkflowAssessment:
        assert step_results[0]["message"] == "已收到文案任务，这是一个初稿占位结果。"
        return WorkflowAssessment(
            intent_satisfied=True,
            rationale="The workflow produced the requested table and draft.",
            answer="已整理来源并生成文档摘要。",
        )


class FailedAssessmentStubLLM(WorkflowStubLLM):
    async def summarize_workflow_result(
        self,
        task: StructuredTask,
        workflow: WorkflowPlan,
        step_results: list[dict[str, object]],
    ) -> WorkflowAssessment:
        raise RuntimeError("Final assessment failed")


class ResearchStubLLM:
    async def plan_workflow(self, task: StructuredTask, skill_catalog: list[dict[str, str]]) -> WorkflowPlan:
        return WorkflowPlan(
            mode="workflow",
            rationale="Current news requires web research.",
            confidence=0.99,
            steps=[
                WorkflowStep(
                    order=1,
                    subtask_id="news",
                    skill_name="search",
                    skill_reason="Current external information is required.",
                    goal="Find two current technology news items.",
                    parameters={
                        "query": "AI 科技",
                        "type": "news",
                        "recency": "day",
                        "limit": 2,
                        "gl": "cn",
                        "hl": "zh-cn",
                    },
                )
            ],
        )

    async def review_search_results(
        self,
        task: StructuredTask,
        step: WorkflowStep,
        attempts: list[dict[str, object]],
        max_tool_calls: int,
    ) -> ResearchAction:
        if len(attempts) == 1:
            return ResearchAction(
                type="tool_call",
                reason="Only one relevant result was found.",
                accepted_urls=["https://example.com/ai"],
                arguments={
                    "query": "芯片 半导体 科技",
                    "type": "news",
                    "recency": "day",
                    "limit": 2,
                    "gl": "cn",
                    "hl": "zh-cn",
                },
            )
        return ResearchAction(
            type="complete",
            reason="Two unique current results are available.",
            accepted_urls=["https://example.com/ai", "https://example.com/chip"],
        )

    async def summarize_workflow_result(
        self,
        task: StructuredTask,
        workflow: WorkflowPlan,
        step_results: list[dict[str, object]],
    ) -> WorkflowAssessment:
        raise AssertionError("Pure search results must bypass the generic final summarizer.")

    async def translate_search_results(self, items: list[dict[str, object]]) -> list[dict[str, str]]:
        return [
            {
                "title": f"第{index}条科技新闻",
                "summary": f"这是第{index}条科技新闻的中文摘要。",
            }
            for index, _ in enumerate(items, start=1)
        ]


class TranslatingResearchStubLLM(ResearchStubLLM):
    async def translate_search_results(self, items: list[dict[str, object]]) -> list[dict[str, str]]:
        assert all(set(item) == {"title", "summary"} for item in items)
        return [
            {"title": f"中文标题{index}", "summary": f"中文摘要{index}"}
            for index, _ in enumerate(items, start=1)
        ]


class UntranslatedResearchStubLLM(ResearchStubLLM):
    async def translate_search_results(self, items: list[dict[str, object]]) -> list[dict[str, str]]:
        return [
            {
                "title": str(item.get("title") or ""),
                "summary": str(item.get("summary") or ""),
            }
            for item in items
        ]


class SelectiveResearchStubLLM(ResearchStubLLM):
    async def review_search_results(
        self,
        task: StructuredTask,
        step: WorkflowStep,
        attempts: list[dict[str, object]],
        max_tool_calls: int,
    ) -> ResearchAction:
        return ResearchAction(
            type="complete",
            reason="Only the AI result is relevant.",
            accepted_urls=["https://example.com/ai"],
        )


class RejectingResearchStubLLM(SelectiveResearchStubLLM):
    async def review_search_results(
        self,
        task: StructuredTask,
        step: WorkflowStep,
        attempts: list[dict[str, object]],
        max_tool_calls: int,
    ) -> ResearchAction:
        return ResearchAction(
            type="complete",
            reason="No result satisfies the request.",
            accepted_urls=[],
        )


class SearchOnlyRegistry:
    def catalog(self) -> list[dict[str, str]]:
        return [{"name": "search", "description": "Current web research"}]

    def available_names(self) -> list[str]:
        return ["search"]


class ResearchExecutorStub:
    def __init__(self) -> None:
        self.registry = SearchOnlyRegistry()
        self.queries: list[str] = []

    async def execute(self, plan):  # type: ignore[no-untyped-def]
        query = str(plan.inputs["parameters"]["query"])
        self.queries.append(query)
        if len(self.queries) == 1:
            results = [
                {
                    "title": "AI news",
                    "link": "https://example.com/ai",
                    "snippet": "AI summary",
                    "date": "1小时前",
                    "source": "Example AI",
                }
            ]
        else:
            results = [
                {
                    "title": "AI news duplicate",
                    "link": "https://example.com/ai",
                    "snippet": "Duplicate",
                    "date": "1小时前",
                    "source": "Example AI",
                },
                {
                    "title": "Chip news",
                    "link": "https://example.com/chip",
                    "snippet": "Chip summary",
                    "date": "2小时前",
                    "source": "Example Chip",
                },
            ]
        return SkillResult(
            ok=True,
            message="raw search status",
            data={
                "provider": "serper",
                "query": query,
                "search_type": "news",
                "recency": "day",
                "time_filter": "qdr:d",
                "retrieved_at": "2026-08-29T12:00:00+08:00",
                "count": len(results),
                "results": results,
            },
        )


def test_agent_returns_direct_answer_without_tool() -> None:
    task = StructuredTask(
        task_type=TaskType.GENERAL,
        user_intent="Ask a casual question",
        normalized_text="How is the weather today?",
    )

    result = asyncio.run(Agent(llm=DirectStubLLM()).run(task))

    assert result.ok is True
    assert "I cannot check weather right now" in result.message
    assert result.data["mode"] == "direct"


def test_agent_executes_multi_step_workflow() -> None:
    task = StructuredTask(
        task_type=TaskType.SEARCH,
        user_intent="Search and write",
        normalized_text="Search the latest tech news and write a document",
    )

    result = asyncio.run(Agent(llm=WorkflowStubLLM()).run(task))

    assert result.ok is True
    assert len(result.data["steps"]) == 2
    assert result.data["steps"][0]["skill_name"] == "copywriter"
    assert result.data["steps"][1]["skill_name"] == "ppt"
    assert result.message == "已整理来源并生成文档摘要。"
    assert "已收到文案任务" not in result.message
    assert result.data["final_assessment"]["intent_satisfied"] is True


def test_agent_never_falls_back_to_raw_skill_message() -> None:
    task = StructuredTask(
        task_type=TaskType.SEARCH,
        user_intent="Search and write",
        normalized_text="Search the latest tech news and write a document",
    )

    with pytest.raises(RuntimeError, match="Final assessment failed"):
        asyncio.run(Agent(llm=FailedAssessmentStubLLM()).run(task))


def test_agent_refines_search_and_deduplicates_results() -> None:
    task = StructuredTask(
        task_type=TaskType.SEARCH,
        user_intent="Find two current technology news items",
        normalized_text="今天最新的2条科技新闻",
    )
    executor = ResearchExecutorStub()

    result = asyncio.run(Agent(llm=ResearchStubLLM(), executor=executor).run(task))  # type: ignore[arg-type]

    assert executor.queries == ["AI 科技", "芯片 半导体 科技"]
    assert "新闻检索结果（共 2 条）" in result.message
    assert result.message.count("https://example.com/") == 2
    assert result.data["steps"][0]["data"]["research_complete"] is True
    assert result.data["steps"][0]["data"]["accepted_urls"] == [
        "https://example.com/ai",
        "https://example.com/chip",
    ]


def test_agent_executes_all_three_planned_search_layers() -> None:
    class PlannedResearchStubLLM(ResearchStubLLM):
        async def plan_workflow(
            self,
            task: StructuredTask,
            skill_catalog: list[dict[str, str]],
        ) -> WorkflowPlan:
            workflow = await super().plan_workflow(task, skill_catalog)
            workflow.steps[0].parameters["planned_queries"] = [
                {"level": 1, "purpose": "核心意图", "query": "AI 科技"},
                {"level": 2, "purpose": "实体与约束补充", "query": "AI 芯片 半导体"},
                {"level": 3, "purpose": "独立角度交叉验证", "query": "AI 科技 来源 对比"},
            ]
            return workflow

    executor = ResearchExecutorStub()
    task = StructuredTask(
        task_type=TaskType.SEARCH,
        user_intent="Find two current technology news items",
        normalized_text="今天最新的2条科技新闻",
    )

    result = asyncio.run(Agent(llm=PlannedResearchStubLLM(), executor=executor).run(task))  # type: ignore[arg-type]

    assert executor.queries == ["AI 科技", "AI 芯片 半导体", "AI 科技 来源 对比"]
    attempts = result.data["steps"][0]["data"]["attempts"]
    assert [attempt["planning_level"] for attempt in attempts] == [1, 2, 3]
    assert result.data["steps"][0]["data"]["planned_queries"][2]["level"] == 3


def test_fast_search_route_uses_deterministic_assessment() -> None:
    task = StructuredTask(
        task_type=TaskType.SEARCH,
        user_intent="昨天10条科技新闻",
        normalized_text="昨天10条科技新闻",
        route_skill="search",
        route_parameters={
            "query": "昨天10条科技新闻",
            "type": "news",
            "recency": "day",
            "limit": 10,
        },
        route_requires_summary=True,
    )

    result = asyncio.run(
        Agent(llm=ResearchStubLLM(), executor=ResearchExecutorStub()).run(task)  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert "raw search status" not in result.message
    assert "找到 1/10 条" in result.message
    assert "https://example.com/ai" in result.message


def test_search_fallback_translates_english_items() -> None:
    task = StructuredTask(
        task_type=TaskType.SEARCH,
        user_intent="Find two current technology news items",
        normalized_text="今天最新的2条科技新闻",
    )
    result = asyncio.run(
        Agent(llm=TranslatingResearchStubLLM(), executor=ResearchExecutorStub()).run(task)  # type: ignore[arg-type]
    )

    assert "中文标题1" in result.message
    assert "中文摘要2" in result.message
    assert result.message.count("https://example.com/") == 2


def test_search_never_outputs_untranslated_english_items() -> None:
    task = StructuredTask(
        task_type=TaskType.SEARCH,
        user_intent="Find two current technology news items",
        normalized_text="今天最新的2条科技新闻",
    )

    result = asyncio.run(
        Agent(llm=UntranslatedResearchStubLLM(), executor=ResearchExecutorStub()).run(task)  # type: ignore[arg-type]
    )

    assert "中文标题和摘要生成失败" in result.message
    assert "AI news" not in result.message
    assert "https://" not in result.message


def test_search_localizes_relative_english_dates() -> None:
    assert Agent._localize_search_date("5 hours ago") == "5小时前"
    assert Agent._localize_search_date("Yesterday") == "昨天"


def test_search_does_not_fill_requested_count_with_unaccepted_results() -> None:
    task = StructuredTask(
        task_type=TaskType.SEARCH,
        user_intent="Find two relevant technology news items",
        normalized_text="今天最新的2条科技新闻",
    )

    result = asyncio.run(
        Agent(llm=SelectiveResearchStubLLM(), executor=ResearchExecutorStub()).run(task)  # type: ignore[arg-type]
    )

    assert "找到 1/2 条" in result.message
    assert "https://example.com/ai" in result.message
    assert "https://example.com/chip" not in result.message
    assert result.data["final_assessment"]["intent_satisfied"] is False


def test_search_returns_clear_zero_result_instead_of_failing() -> None:
    task = StructuredTask(
        task_type=TaskType.SEARCH,
        user_intent="Find today's policy news",
        normalized_text="今天最新出台的10条中国政策新闻",
    )

    result = asyncio.run(
        Agent(llm=RejectingResearchStubLLM(), executor=ResearchExecutorStub()).run(task)  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert "已完成 3 轮检索" in result.message
    assert "未使用无关内容补足数量" in result.message
    assert "http" not in result.message


def test_workflow_validation_rejects_non_array_excel_rows() -> None:
    workflow = WorkflowPlan(
        mode="workflow",
        rationale="Create a workbook",
        confidence=0.99,
        steps=[
            WorkflowStep(
                order=1,
                subtask_id="excel",
                skill_name="excel",
                skill_reason="Create the requested workbook",
                goal="Create workbook",
                parameters={
                    "operation": "create",
                    "filename": "report.xlsx",
                    "workbook_spec": {"sheets": [{"name": "Data", "rows": 10}]},
                },
            )
        ],
    )

    error = LLMClient.__new__(LLMClient)._validate_workflow_plan(workflow)

    assert "rows must be an array" in error


def test_inline_csv_excel_request_has_excel_only_fallback() -> None:
    task = StructuredTask(
        task_type=TaskType.EXCEL,
        user_intent="将员工数据生成Excel表格",
        normalized_text="生成员工Excel表格",
        source_text="工号,姓名\nEMP001,张伟\n生成excel表",
    )

    workflow = Agent._fallback_inline_excel_workflow(task)

    assert workflow is not None
    assert len(workflow.steps) == 1
    assert workflow.steps[0].skill_name == "excel"
    assert workflow.steps[0].parameters["workbook_spec"]["sheets"][0]["rows"] == []


def test_non_excel_request_never_uses_excel_fallback() -> None:
    task = StructuredTask(
        task_type=TaskType.SEARCH,
        user_intent="搜索科技新闻",
        normalized_text="搜索科技新闻",
        source_text="搜索今天的10条科技新闻",
    )

    assert Agent._fallback_inline_excel_workflow(task) is None
