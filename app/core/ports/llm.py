# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Protocol

from app.domain.contracts import (
    ResearchAction,
    RouteDecision,
    StructuredTask,
    TaskExtraction,
    WorkflowAssessment,
    WorkflowPlan,
    WorkflowStep,
)


class TaskExtractor(Protocol):
    async def extract_task(self, text: str) -> TaskExtraction: ...


class TaskRouter(Protocol):
    async def route_task(
        self,
        text: str,
        attachments: list[dict[str, Any]],
        skill_catalog: list[dict[str, str]],
    ) -> RouteDecision: ...


class ToolInputAnalyzer(Protocol):
    async def analyze_tool_input(
        self,
        text: str,
        skill_name: str,
        attachments: list[dict[str, Any]],
    ) -> dict[str, Any]: ...


class WorkflowPlanner(Protocol):
    async def plan_workflow(
        self,
        task: StructuredTask,
        skill_catalog: list[dict[str, str]],
    ) -> WorkflowPlan: ...


class ResultJudge(Protocol):
    async def summarize_workflow_result(
        self,
        task: StructuredTask,
        workflow: WorkflowPlan,
        step_results: list[dict[str, Any]],
    ) -> WorkflowAssessment: ...


class SearchSupervisor(Protocol):
    async def review_search_results(
        self,
        task: StructuredTask,
        step: WorkflowStep,
        attempts: list[dict[str, Any]],
        max_tool_calls: int,
    ) -> ResearchAction: ...


class SearchTranslator(Protocol):
    async def translate_search_results(
        self,
        items: list[dict[str, Any]],
    ) -> list[dict[str, str]]: ...
