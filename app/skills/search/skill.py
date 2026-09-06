# -*- coding: utf-8 -*-
from app.domain.contracts import SkillContext, SkillResult
from app.skills.base import Skill
from app.skills.search.executor import SearchExecutor


class SearchSkill(Skill):
    name = "search"
    description = (
        "Search current, verifiable web and news sources with explicit freshness filters. "
        "When the intent router selects this skill, use the user's complete current-turn request "
        "as the planning subject and generate exactly three hierarchical search queries before "
        "searching: (1) the direct core-intent query, (2) a complementary entity/constraint "
        "query, and (3) an independent validation or alternative-angle query. "
        "Keep every explicit time, language, location, and quantity constraint, while removing "
        "conversation and output-format wording. Pass them as parameters.planned_queries, an "
        "ordered list of three objects with level, purpose, and query; parameters.query must "
        "equal the first query. Execute all three layers when the request is a pure search, "
        "deduplicate results, and keep source URLs for every accepted result."
    )

    def __init__(self, executor: SearchExecutor | None = None) -> None:
        self.executor = executor or SearchExecutor()

    async def run(self, inputs: SkillContext | dict[str, object]) -> SkillResult:
        context = self.context(inputs)
        data = await self.executor.execute(context.to_executor_input())
        # Preserve the model's search plan in the structured result so callers can
        # audit which dimensions were searched alongside the provider results.
        planned_queries = context.parameters.get("planned_queries")
        if isinstance(planned_queries, list):
            data["planned_queries"] = planned_queries
        return SkillResult(
            ok=True,
            message=f"Serper 检索完成，共返回 {data.get('count', 0)} 条结果。",
            data=data,
        )
