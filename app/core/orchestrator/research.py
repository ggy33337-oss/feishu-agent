# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any

from app.core.orchestrator.executor import Executor
from app.core.ports.llm import SearchSupervisor, SearchTranslator
from app.domain.contracts import (
    Plan,
    ResearchAction,
    SkillResult,
    StructuredTask,
    WorkflowAssessment,
    WorkflowStep,
)
from app.services.timing import timed_stage

import logging


logger = logging.getLogger(__name__)


class ResearchRunner:
    """Execute and assess the bounded iterative search workflow."""

    DEFAULT_RESULT_LIMIT = 10

    def __init__(
        self,
        executor: Executor,
        supervisor: SearchSupervisor,
        translator: SearchTranslator,
        max_tool_calls: int = 3,
    ) -> None:
        self.executor = executor
        self.supervisor = supervisor
        self.translator = translator
        self.max_tool_calls = max_tool_calls

    async def run(
        self,
        task: StructuredTask,
        step: WorkflowStep,
        plan: Plan,
        job_id: str | None = None,
    ) -> SkillResult:
        attempts: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        final_reason = "Search call budget exhausted."
        research_complete = False
        accepted_urls: list[str] = []
        accepted_url_keys: set[str] = set()
        requested_limit = self.requested_result_limit(task)
        planned_queries = self.planned_search_queries(step)
        if "planned_queries" in step.parameters and len(planned_queries) < 3:
            planned_queries = self.complete_search_queries(task, step, planned_queries)
        planned_query_specs = self.query_specs(step, planned_queries)
        if planned_query_specs:
            # Keep the step contract canonical for the executor, supervisor,
            # and returned audit payload even when the model omitted fields.
            step.parameters["query"] = planned_query_specs[0]["query"]
            step.parameters["planned_queries"] = planned_query_specs

        # The search skill asks the planner for three complementary query
        # layers. Seed the first call from that plan rather than from the raw
        # conversational request. The supervisor can still refine a layer when
        # a plan was not supplied by an older caller.
        if planned_queries:
            first_query = planned_queries[0]
            plan.inputs["text"] = first_query
            plan.inputs["parameters"] = {
                **dict(step.parameters),
                "query": first_query,
            }

        for attempt_number in range(1, self.max_tool_calls + 1):
            if attempt_number <= len(planned_queries):
                query = planned_queries[attempt_number - 1]
                plan.inputs["text"] = query
                plan.inputs["parameters"] = {
                    **dict(step.parameters),
                    "query": query,
                    "planned_queries": step.parameters.get("planned_queries", []),
                }
            async with timed_stage(
                logger,
                "search.tool",
                job_id=job_id,
                fields={
                    "task_id": task.task_id,
                    "step_id": step.step_id,
                    "attempt": attempt_number,
                    "skill": step.skill_name,
                },
            ):
                result = await self.executor.execute(plan)
            artifacts.extend(result.artifacts)
            attempts.append(
                {
                    "attempt": attempt_number,
                    "planning_level": attempt_number if attempt_number <= len(planned_queries) else None,
                    "query": result.data.get("query"),
                    "search_type": result.data.get("search_type"),
                    "recency": result.data.get("recency"),
                    "time_filter": result.data.get("time_filter"),
                    "retrieved_at": result.data.get("retrieved_at"),
                    "count": result.data.get("count", 0),
                    "results": result.data.get("results", []),
                }
            )
            try:
                async with timed_stage(
                    logger,
                    "search.review",
                    job_id=job_id,
                    fields={
                        "task_id": task.task_id,
                        "step_id": step.step_id,
                        "attempt": attempt_number,
                        "result_count": result.data.get("count", 0),
                    },
                ):
                    action = await self.supervisor.review_search_results(
                        task,
                        step,
                        attempts,
                        self.max_tool_calls,
                    )
            except Exception as exc:
                # A slow/unavailable reviewer must not discard usable search
                # results. Fall back to deterministic topical ranking for this
                # attempt and let the normal result limit decide completion.
                logger.warning("Search review failed; using deterministic fallback: %s", exc)
                fallback_items = self.rank_search_results(
                    [item for item in result.data.get("results", []) if isinstance(item, dict)],
                    task.normalized_text,
                )
                action = ResearchAction(
                    type="complete",
                    reason="审查模型超时，已使用确定性相关性排序保留当前搜索结果。",
                    accepted_urls=[
                        str(item.get("link") or "").strip()
                        for item in fallback_items
                        if str(item.get("link") or "").strip()
                    ],
                )
            final_reason = action.reason
            for url in action.accepted_urls:
                normalized = str(url).strip().lower().rstrip("/")
                if normalized and normalized not in accepted_url_keys:
                    accepted_url_keys.add(normalized)
                    accepted_urls.append(str(url).strip())
            if requested_limit is not None and len(accepted_url_keys) >= requested_limit:
                research_complete = True
                # The default request asks for ten results. Once one review
                # confirms ten relevant, source-backed URLs, stop immediately
                # instead of paying for the remaining planned query layers.
                # Smaller explicit requests retain the three-layer validation
                # behavior used by existing callers.
                if requested_limit >= self.DEFAULT_RESULT_LIMIT:
                    break
            if attempt_number >= self.max_tool_calls:
                break

            # Execute the next planned dimension even when an earlier layer
            # already looked sufficient; the three-layer contract is intended
            # to improve coverage, not just provide a retry fallback.
            if attempt_number < len(planned_queries):
                continue

            if planned_queries and action.type == "complete":
                break

            next_parameters = dict(action.arguments)
            if not next_parameters.get("query"):
                next_parameters = self.fallback_search_parameters(task, step, attempts)
            next_query = str(next_parameters.get("query") or "").strip()
            if not next_query:
                break
            plan.inputs["text"] = next_query
            plan.inputs["parameters"] = next_parameters

        combined = self.deduplicate_search_results(attempts)
        accepted = {url.strip().lower().rstrip("/") for url in accepted_urls}
        selected = [
            item
            for item in combined
            if str(item.get("link") or "").strip().lower().rstrip("/") in accepted
        ]
        selected = self.rank_search_results(selected, task.normalized_text)
        selected = selected[: (requested_limit or self.DEFAULT_RESULT_LIMIT)]
        return SkillResult(
            ok=True,
            message=f"检索研究完成，共获得 {len(selected)} 条去重结果。",
            artifacts=artifacts,
            data={
                "provider": "serper",
                "count": len(selected),
                "requested_limit": requested_limit,
                "results": selected,
                "attempts": attempts,
                "planned_queries": planned_query_specs,
                "research_complete": research_complete,
                "research_reason": final_reason,
                "accepted_urls": [str(item.get("link") or "").strip() for item in selected],
            },
        )

    async def build_assessment(
        self,
        task: StructuredTask,
        step_results: list[dict[str, Any]],
        job_id: str | None = None,
    ) -> WorkflowAssessment:
        search_data = next(
            (
                step.get("data")
                for step in step_results
                if step.get("skill_name") == "search" and isinstance(step.get("data"), dict)
            ),
            None,
        )
        if not isinstance(search_data, dict):
            return WorkflowAssessment(
                intent_satisfied=False,
                rationale="搜索步骤没有返回结构化结果。",
                answer="本次检索没有返回可整理的结果，请稍后重试。",
                missing_information=["缺少结构化搜索结果"],
            )
        results = search_data.get("results")
        if not isinstance(results, list):
            results = []
        requested = self.requested_search_limit_from_task(task, step_results, len(results))
        selected = [
            item
            for item in results
            if isinstance(item, dict)
            and str(item.get("title") or "").strip()
            and str(item.get("link") or "").strip()
        ]
        selected = self.rank_search_results(selected, task.normalized_text)
        selected = selected[:requested]
        if not selected:
            attempts = search_data.get("attempts")
            attempt_count = len(attempts) if isinstance(attempts, list) else 0
            request_text = re.sub(r"\s+", " ", task.normalized_text).strip() or "当前请求"
            return WorkflowAssessment(
                intent_satisfied=False,
                rationale="搜索结果中没有同时包含标题和来源 URL 的有效条目。",
                answer=(
                    f"已完成 {attempt_count} 轮检索，但在“{request_text}”的限定条件下，"
                    "没有找到同时满足相关性和来源要求的有效结果。为避免误导，未使用无关内容补足数量。"
                ),
                missing_information=["缺少带来源 URL 的有效结果"],
            )

        try:
            async with timed_stage(
                logger,
                "search.translate",
                job_id=job_id,
                fields={"task_id": task.task_id, "count": len(selected)},
            ):
                translated = await self.translator.translate_search_results(
                    [
                        {
                            "title": str(item.get("title") or "").strip(),
                            "summary": str(item.get("snippet") or item.get("title") or "").strip(),
                        }
                        for item in selected
                    ]
                )
            if not self.valid_chinese_search_summaries(translated, len(selected)):
                raise RuntimeError("Chinese news summarizer returned untranslated content.")
        except Exception:
            return WorkflowAssessment(
                intent_satisfied=False,
                rationale="已获得有效搜索结果，但中文标题和摘要生成失败。",
                answer=(
                    f"已检索到 {len(selected)} 条有效来源，但中文标题和摘要生成失败。"
                    "为避免直接返回未翻译的英文内容，本次未输出新闻列表，请稍后重试。"
                ),
                missing_information=["缺少经过校验的中文标题和摘要"],
            )

        complete = requested is None or len(selected) >= requested
        count_text = f"共 {len(selected)} 条" if complete else f"找到 {len(selected)}/{requested} 条"
        lines = [f"新闻检索结果（{count_text}）", ""]
        for index, item in enumerate(selected, start=1):
            translation = translated[index - 1]
            lines.extend(
                [
                    f"{index}. {str(translation['title']).strip()}",
                    f"来源：{str(item.get('source') or '未知来源').strip()} | "
                    f"时间：{self.localize_search_date(str(item.get('date') or '时间未提供'))}",
                    f"摘要：{str(translation['summary']).strip()}",
                    f"链接：{str(item.get('link') or '').strip()}",
                    "",
                ]
            )
        missing_information: list[str] = []
        if not complete:
            gap = f"限定条件下仅获得 {len(selected)} 条有效结果，少于请求的 {requested} 条。"
            lines.append(gap)
            missing_information.append(gap)
        return WorkflowAssessment(
            intent_satisfied=complete,
            rationale="程序直接从多轮检索的结构化结果组装输出，并保留每条原始来源 URL。",
            answer="\n".join(lines).strip(),
            missing_information=missing_information,
        )

    @staticmethod
    def planned_search_queries(step: WorkflowStep) -> list[str]:
        """Read and normalize the three-level query plan from step parameters."""
        raw = step.parameters.get("planned_queries")
        if not isinstance(raw, list):
            return []
        queries: list[str] = []
        seen: set[str] = set()
        for item in raw:
            value = item.get("query") if isinstance(item, dict) else item
            query = str(value or "").strip()
            key = query.casefold()
            if query and key not in seen:
                seen.add(key)
                queries.append(query)
            if len(queries) >= 3:
                break
        return queries

    @classmethod
    def complete_search_queries(
        cls,
        task: StructuredTask,
        step: WorkflowStep,
        queries: list[str],
    ) -> list[str]:
        """Fill malformed model plans to the required three distinct angles."""
        base = queries[0] if queries else str(step.parameters.get("query") or task.normalized_text)
        base = cls.clean_search_query(base) or task.normalized_text.strip()
        defaults = (
            f"{base} 关键实体 相关信息",
            f"{base} 来源 对比 核实",
        )
        completed = list(queries[:3])
        used = {item.casefold() for item in completed}
        for candidate in defaults:
            if len(completed) >= 3:
                break
            if candidate.casefold() not in used:
                completed.append(candidate)
                used.add(candidate.casefold())
        while len(completed) < 3:
            candidate = f"{base} 角度{len(completed) + 1}"
            if candidate.casefold() not in used:
                completed.append(candidate)
                used.add(candidate.casefold())
        return completed

    @staticmethod
    def clean_search_query(value: str) -> str:
        cleaned = re.sub(r"\d+\s*条", "", str(value or ""))
        cleaned = re.sub(r"^(?:请|帮我)?\s*(?:搜索|检索|查找|搜一下|查一下)\s*", "", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def query_specs(step: WorkflowStep, queries: list[str]) -> list[dict[str, Any]]:
        raw = step.parameters.get("planned_queries")
        purposes = {
            str(item.get("query") or "").strip().casefold(): str(item.get("purpose") or "").strip()
            for item in raw
            if isinstance(item, dict)
        } if isinstance(raw, list) else {}
        defaults = ("核心意图", "实体与约束补充", "独立角度交叉验证")
        return [
            {
                "level": index,
                "purpose": purposes.get(query.casefold()) or defaults[index - 1],
                "query": query,
            }
            for index, query in enumerate(queries[:3], start=1)
        ]

    @staticmethod
    def fallback_search_parameters(
        task: StructuredTask,
        step: WorkflowStep,
        attempts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        base_query = str(step.parameters.get("query") or task.normalized_text).strip()
        previous = {str(item.get("query") or "").strip().lower() for item in attempts}
        for suffix in ("AI 芯片 半导体", "大模型 人工智能 机器人", "科技产品 发布 突破"):
            query = f"{base_query} {suffix}".strip()
            if query.lower() not in previous:
                return {
                    "query": query,
                    "type": str(step.parameters.get("type") or "news"),
                    "recency": step.parameters.get("recency") or "day",
                    "limit": min(ResearchRunner.requested_search_limit(step), 10),
                    "gl": step.parameters.get("gl") or "cn",
                    "hl": step.parameters.get("hl") or "zh-cn",
                }
        return {}

    @staticmethod
    def requested_search_limit(step: WorkflowStep) -> int:
        try:
            return max(1, min(int(step.parameters.get("limit", 10)), 20))
        except (TypeError, ValueError):
            return 10

    @staticmethod
    def requested_result_limit(task: StructuredTask) -> int:
        """Extract an explicit result target, defaulting to ten results."""
        text = str(task.normalized_text or "")
        match = re.search(r"(?:前|最少|至少|返回|提供|给我|给出|列出|找出|数量|条数)\s*(\d+)\s*(?:条|个|篇|项|items?)", text, re.I)
        if not match:
            match = re.search(r"\b(\d+)\s*(?:条|个|篇|项|items?)\b", text, re.I)
        # Some legacy callers pass text that has already lost its CJK unit
        # characters; retain their numeric target without treating dates as a
        # count by requiring a small result-like number.
        if not match:
            match = re.search(r"(?<!\d)([1-9]|1\d|20)(?!\d)", text)
        return max(1, min(int(match.group(1)), 20)) if match else ResearchRunner.DEFAULT_RESULT_LIMIT

    @staticmethod
    def rank_search_results(results: list[dict[str, Any]], request_text: str) -> list[dict[str, Any]]:
        """Rank results by topical relevance while preserving provider order for ties."""
        terms = (
            "算力", "人工智能", "ai", "芯片", "gpu", "服务器", "数据中心",
            "大模型", "云计算", "半导体", "推理", "token", "模型训练",
        )
        request = str(request_text or "").casefold()
        requested_terms = tuple(term for term in terms if term in request)
        focus_terms = requested_terms or terms

        def score(item: dict[str, Any]) -> int:
            title = str(item.get("title") or "").casefold()
            summary = str(item.get("snippet") or item.get("summary") or "").casefold()
            return sum((3 if term in title else 0) + (1 if term in summary else 0) for term in focus_terms)

        ranked = sorted(enumerate(results), key=lambda pair: (-score(pair[1]), pair[0]))
        return [item for _, item in ranked]

    @staticmethod
    def deduplicate_search_results(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for attempt in attempts:
            results = attempt.get("results", [])
            if not isinstance(results, list):
                continue
            for item in results:
                if not isinstance(item, dict):
                    continue
                link = str(item.get("link") or "").strip().lower().rstrip("/")
                title = re.sub(
                    r"[^0-9a-z\u4e00-\u9fff]+",
                    "",
                    re.sub(r"[\[\(（【].*?[\]\)）】]", "", str(item.get("title") or "").lower()),
                )
                identity = f"url:{link}" if link else f"title:{title}|{item.get('source', '')}"
                title_identity = f"title:{title}" if title else ""
                if identity in seen or (title_identity and title_identity in seen):
                    continue
                seen.add(identity)
                if title_identity:
                    seen.add(title_identity)
                unique.append(item)
        return unique

    @staticmethod
    def valid_chinese_search_summaries(items: Any, expected_count: int) -> bool:
        if not isinstance(items, list) or len(items) != expected_count:
            return False
        return all(
            isinstance(item, dict)
            and re.search(r"[\u4e00-\u9fff]", str(item.get("title") or ""))
            and re.search(r"[\u4e00-\u9fff]", str(item.get("summary") or ""))
            for item in items
        )

    @staticmethod
    def localize_search_date(value: str) -> str:
        normalized = value.strip()
        patterns = (
            (r"^(\d+)\s*(?:minutes?|mins?)\s+ago$", "分钟前"),
            (r"^(\d+)\s*(?:hours?|hrs?)\s+ago$", "小时前"),
            (r"^(\d+)\s*days?\s+ago$", "天前"),
            (r"^(\d+)\s*weeks?\s+ago$", "周前"),
            (r"^(\d+)\s*months?\s+ago$", "个月前"),
        )
        for pattern, suffix in patterns:
            match = re.match(pattern, normalized, re.I)
            if match:
                return f"{match.group(1)}{suffix}"
        return "昨天" if normalized.lower() == "yesterday" else normalized

    @staticmethod
    def requested_search_limit_from_task(
        task: StructuredTask,
        step_results: list[dict[str, Any]],
        fallback: int,
    ) -> int | None:
        return ResearchRunner.requested_result_limit(task)

        # Legacy fallback retained below for reference; explicit user intent
        # is authoritative and provider defaults must not become a target.
        # pragma: no cover
        for step in step_results:
            data = step.get("data")
            if isinstance(data, dict) and isinstance(data.get("requested_limit"), int):
                return data["requested_limit"]
        match = re.search(
            r"(?:前|取|共|数量|条)\s*(\d+)\s*条|(?:^|[^\d])(\d+)\s*(?:条|items?)",
            task.normalized_text,
            re.I,
        )
        if match:
            return max(1, min(int(next(group for group in match.groups() if group)), 20))
        return max(1, min(fallback, 20))
