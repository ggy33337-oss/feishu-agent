# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from app.domain.contracts import (
    ResearchAction,
    StructuredTask,
    TaskExtraction,
    WorkflowAssessment,
    WorkflowPlan,
    WorkflowStep,
)
from app.models.llm import LLMClient


class TaskExtractionService:
    def __init__(self, provider: LLMClient) -> None:
        self.provider = provider

    async def extract_task(self, text: str) -> TaskExtraction:
        return await self.provider.extract_task(text)


class WorkflowPlanningService:
    def __init__(self, provider: LLMClient) -> None:
        self.provider = provider

    async def plan_workflow(
        self,
        task: StructuredTask,
        skill_catalog: list[dict[str, str]],
    ) -> WorkflowPlan:
        return await self.provider.plan_workflow(task, skill_catalog)


class WorkflowResultService:
    def __init__(self, provider: LLMClient) -> None:
        self.provider = provider

    async def summarize_workflow_result(
        self,
        task: StructuredTask,
        workflow: WorkflowPlan,
        step_results: list[dict[str, Any]],
    ) -> WorkflowAssessment:
        return await self.provider.summarize_workflow_result(task, workflow, step_results)


class SearchReviewService:
    def __init__(self, provider: LLMClient) -> None:
        self.provider = provider

    async def review_search_results(
        self,
        task: StructuredTask,
        step: WorkflowStep,
        attempts: list[dict[str, Any]],
        max_tool_calls: int,
    ) -> ResearchAction:
        return await self.provider.review_search_results(task, step, attempts, max_tool_calls)


class SearchTranslationService:
    def __init__(self, provider: LLMClient) -> None:
        self.provider = provider

    async def translate_search_results(
        self,
        items: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        return await self.provider.translate_search_results(items)

