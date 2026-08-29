import asyncio

from app.core.orchestrator.agent import Agent
from app.core.parser.schemas import RouteDecision, StructuredTask, TaskType


class DirectStubLLM:
    async def select_skill(self, task: StructuredTask, available_skills: list[str]) -> RouteDecision:
        return RouteDecision(
            mode="direct",
            skill_name=None,
            answer="今天的天气我暂时不能实时查询，但可以帮你接搜索工具。",
            rationale="No external tool required",
            confidence=0.91,
        )


class ToolStubLLM:
    async def select_skill(self, task: StructuredTask, available_skills: list[str]) -> RouteDecision:
        return RouteDecision(
            mode="tool",
            skill_name="search",
            answer=None,
            rationale="Needs search",
            confidence=0.97,
        )


def test_agent_returns_direct_answer_without_tool() -> None:
    task = StructuredTask(
        task_type=TaskType.GENERAL,
        user_intent="Ask a casual question",
        normalized_text="今天天气怎么样",
    )

    result = asyncio.run(Agent(llm=DirectStubLLM()).run(task))

    assert result.ok is True
    assert "暂时不能实时查询" in result.message
    assert result.data["mode"] == "direct"


def test_agent_dispatches_to_selected_skill() -> None:
    task = StructuredTask(
        task_type=TaskType.SEARCH,
        user_intent="Find industry sources",
        normalized_text="搜索行业资料",
    )

    result = asyncio.run(Agent(llm=ToolStubLLM()).run(task))

    assert result.ok is True
    assert "检索" in result.message
