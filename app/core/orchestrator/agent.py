from app.core.orchestrator.executor import Executor
from app.core.orchestrator.planner import Planner
from app.core.parser.schemas import SkillResult, StructuredTask
from app.models.llm import LLMClient


class Agent:
    """Top-level coordinator for parse -> LLM route -> execute workflows."""

    def __init__(
        self,
        llm: LLMClient | None = None,
        planner: Planner | None = None,
        executor: Executor | None = None,
    ) -> None:
        self.llm = llm or LLMClient()
        self.planner = planner or Planner()
        self.executor = executor or Executor()

    async def run(self, task: StructuredTask) -> SkillResult:
        available_skills = self.executor.registry.available_names()
        if "feishu_lark_agent" in available_skills:
            available_skills = [
                "feishu_lark_agent",
                *[name for name in available_skills if name != "feishu_lark_agent"],
            ]

        decision = await self.llm.select_skill(task, available_skills)
        if decision.mode == "direct":
            if not decision.answer:
                raise ValueError("LLM returned direct mode without an answer.")
            return SkillResult(
                ok=True,
                message=decision.answer,
                data={
                    "mode": decision.mode,
                    "rationale": decision.rationale,
                    "confidence": decision.confidence,
                },
            )

        if decision.skill_name not in available_skills:
            raise ValueError(
                f"LLM selected unknown skill '{decision.skill_name}'. Available: {', '.join(sorted(available_skills))}"
            )

        plan = self.planner.create_plan(task, decision)
        return await self.executor.execute(plan)
