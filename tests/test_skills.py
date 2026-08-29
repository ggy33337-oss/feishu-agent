import asyncio

from app.skills.registry import SkillRegistry
from app.skills.feishu_lark_agent.executor import FeishuLarkAgentExecutor
from app.skills.feishu_lark_agent.skill import FeishuLarkAgentSkill


def test_default_registry_contains_core_skills() -> None:
    registry = SkillRegistry.default()

    result = asyncio.run(registry.get("excel").run({"text": "分析表格"}))

    assert result.ok is True
    assert result.data["summary"] == "Excel task accepted"


def test_registry_contains_feishu_lark_skill() -> None:
    registry = SkillRegistry.default()

    assert "feishu_lark_agent" in registry.available_names()


def test_feishu_lark_executor_resolves_command_shape() -> None:
    executor = FeishuLarkAgentExecutor(script_path="app/skills/feishu_lark_agent/feishu.py")
    category, action, flags = executor._resolve_command(
        {
            "parameters": {
                "category": "msg",
                "action": "send",
                "flags": {"to": "oc_test", "text": "hello"},
            }
        }
    )

    assert category == "msg"
    assert action == "send"
    assert flags["to"] == "oc_test"


def test_feishu_lark_skill_formats_urls() -> None:
    skill = FeishuLarkAgentSkill()

    assert "https://example.com/doc" in skill._format_message({"url": "https://example.com/doc"})
