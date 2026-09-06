# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from typing import Any

from app.core.orchestrator.dag import topological_batches
from app.core.orchestrator.executor import Executor
from app.core.orchestrator.planner import Planner
from app.core.orchestrator.research import ResearchRunner
from app.core.ports.llm import (
    ResultJudge,
    SearchSupervisor,
    SearchTranslator,
    WorkflowPlanner,
)
from app.domain.contracts import (
    SkillResult,
    StructuredTask,
    TaskType,
    WorkflowPlan,
    WorkflowStep,
)
from app.models.llm import LLMClient
from app.services.timing import timed_stage
from app.core.orchestrator.stages import PipelineStage

import logging


logger = logging.getLogger(__name__)


class Agent:
    """Plan a task and execute its dependency graph through registered skills."""

    max_search_tool_calls = 3

    def __init__(
        self,
        llm: object | None = None,
        planner: Planner | None = None,
        executor: Executor | None = None,
        workflow_planner: WorkflowPlanner | None = None,
        result_judge: ResultJudge | None = None,
        search_supervisor: SearchSupervisor | None = None,
        search_translator: SearchTranslator | None = None,
        research_runner: ResearchRunner | None = None,
    ) -> None:
        shared_llm = llm or LLMClient()
        self.llm = shared_llm
        self.workflow_planner = workflow_planner or shared_llm  # type: ignore[assignment]
        self.result_judge = result_judge or shared_llm  # type: ignore[assignment]
        self.planner = planner or Planner()
        self.executor = executor or Executor()
        self.research_runner = research_runner or ResearchRunner(
            executor=self.executor,
            supervisor=search_supervisor or shared_llm,  # type: ignore[arg-type]
            translator=search_translator or shared_llm,  # type: ignore[arg-type]
            max_tool_calls=self.max_search_tool_calls,
        )

    async def run(self, task: StructuredTask, job_id: str | None = None) -> SkillResult:
        if task.route_skill or task.route_answer:
            return await self._run_fast(task, job_id=job_id)

        skill_catalog = self.executor.registry.catalog()
        try:
            async with timed_stage(
                logger,
                PipelineStage.SKILL_ROUTER,
                job_id=job_id,
                fields={"legacy_stage": "workflow.plan"},
            ):
                workflow = await self.workflow_planner.plan_workflow(task, skill_catalog)
        except RuntimeError:
            workflow = self._fallback_inline_excel_workflow(task)
            if workflow is None:
                raise
        if self._inline_excel_creation_requested(task) and (
            workflow.mode != "workflow"
            or not any(step.skill_name == "excel" for step in workflow.steps)
        ):
            workflow = self._fallback_inline_excel_workflow(task) or workflow
        workflow = self._normalize_workflow(task, workflow)

        if workflow.mode == "direct":
            if not workflow.answer:
                raise ValueError("LLM returned direct mode without an answer.")
            async with timed_stage(
                logger,
                PipelineStage.CHAT_MODEL,
                job_id=job_id,
                fields={"task_id": task.task_id},
            ):
                return SkillResult(
                    ok=True,
                    message=workflow.answer,
                    data={
                        "mode": workflow.mode,
                        "rationale": workflow.rationale,
                        "confidence": workflow.confidence,
                    },
                )

        available = set(self.executor.registry.available_names())
        unknown = sorted({step.skill_name for step in workflow.steps} - available)
        if unknown:
            raise ValueError(
                f"Workflow selected unknown skills: {', '.join(unknown)}. "
                f"Available: {', '.join(sorted(available))}"
            )

        results_by_id: dict[str, dict[str, Any]] = {}
        for batch in topological_batches(workflow.steps):
            completed = await asyncio.gather(
                *(self._execute_step(task, step, results_by_id, job_id=job_id) for step in batch)
            )
            results_by_id.update({item["step_id"]: item for item in completed})

        step_results = [results_by_id[step.step_id] for step in sorted(workflow.steps, key=lambda item: item.order)]
        artifacts = [
            artifact
            for step_result in step_results
            for artifact in step_result.get("artifacts", [])
        ]
        if self._is_search_only_workflow(task, workflow):
            async with timed_stage(
                logger,
                PipelineStage.RESULT_MODEL,
                job_id=job_id,
                fields={"task_id": task.task_id, "legacy_stage": "search.assessment"},
            ):
                assessment = await self.research_runner.build_assessment(
                    task,
                    step_results,
                    job_id=job_id,
                )
        else:
            async with timed_stage(
                logger,
                PipelineStage.RESULT_MODEL,
                job_id=job_id,
                fields={"legacy_stage": "workflow.assessment"},
            ):
                assessment = await self.result_judge.summarize_workflow_result(
                    task,
                    workflow,
                    step_results,
                )

        return SkillResult(
            ok=True,
            message=assessment.answer,
            artifacts=artifacts,
            data={
                "mode": workflow.mode,
                "rationale": workflow.rationale,
                "confidence": workflow.confidence,
                "subtasks": [subtask.model_dump() for subtask in workflow.subtasks],
                "steps": step_results,
                "final_assessment": {
                    "intent_satisfied": assessment.intent_satisfied,
                    "rationale": assessment.rationale,
                    "missing_information": assessment.missing_information,
                },
            },
        )

    async def _run_fast(self, task: StructuredTask, job_id: str | None = None) -> SkillResult:
        """Execute the single route without planning, DAG, or research loops."""
        if task.route_answer and not task.route_skill:
            async with timed_stage(
                logger,
                PipelineStage.CHAT_MODEL,
                job_id=job_id,
                fields={"task_id": task.task_id},
            ):
                return SkillResult(
                    ok=True,
                    message=task.route_answer,
                    data={"mode": "direct", "route_reason": task.route_reason},
                )
        skill_name = task.route_skill or task.task_type.value
        if skill_name not in set(self.executor.registry.available_names()):
            raise ValueError(f"Workflow selected unknown skills: {skill_name}")
        step = WorkflowStep(
            order=1,
            subtask_id=task.subtasks[0].subtask_id if task.subtasks else "route",
            skill_name=skill_name,
            skill_reason=task.route_reason or "单步路由",
            goal=task.user_intent,
            parameters=dict(task.route_parameters),
        )
        plan = self.planner.create_plan(task, step)
        plan.inputs["job_id"] = job_id
        async with timed_stage(
            logger,
            f"{PipelineStage.SKILL}.{skill_name}",
            job_id=job_id,
                fields={"step_id": step.step_id, "task_id": task.task_id},
        ):
            # Route search requests through the same bounded research runner
            # as workflow searches so the skill's three-layer query plan is
            # honored consistently for both intent-router paths.
            if skill_name == "search" and task.route_parameters.get("planned_queries"):
                result = await self.research_runner.run(task, step, plan, job_id=job_id)
            else:
                result = await self.executor.execute(plan)
        step_result = {
            "step_id": step.step_id,
            "subtask_id": step.subtask_id,
            "skill_name": skill_name,
            "message": result.message,
            "data": result.data,
            "artifacts": result.artifacts,
        }
        if not task.route_requires_summary:
            return result
        workflow = WorkflowPlan(
            mode="workflow",
            rationale=task.route_reason or "单步路由",
            confidence=1.0,
            subtasks=task.subtasks,
            steps=[step],
        )
        try:
            async with timed_stage(
                logger,
                PipelineStage.RESULT_MODEL,
                job_id=job_id,
                fields={
                    "task_id": task.task_id,
                    "legacy_stage": "response.summary",
                    "skill_name": skill_name,
                },
            ):
                if skill_name == "search":
                    # Search results have a dedicated formatter that preserves
                    # every source URL instead of asking a generic judge to
                    # reproduce links from a large result payload.
                    assessment = await self.research_runner.build_assessment(
                        task,
                        [step_result],
                        job_id=job_id,
                    )
                else:
                    assessment = await self.result_judge.summarize_workflow_result(
                        task,
                        workflow,
                        [step_result],
                    )
            return SkillResult(
                ok=True,
                message=assessment.answer,
                artifacts=result.artifacts,
                data={
                    "mode": "tool",
                    "route_reason": task.route_reason,
                    "step": step_result,
                    "final_assessment": {
                        "intent_satisfied": assessment.intent_satisfied,
                        "rationale": assessment.rationale,
                        "missing_information": assessment.missing_information,
                    },
                },
            )
        except RuntimeError:
            logger.warning("Response summary failed; returning deterministic skill result.")
            return result

    async def _execute_step(
        self,
        task: StructuredTask,
        step: WorkflowStep,
        results_by_id: dict[str, dict[str, Any]],
        job_id: str | None = None,
    ) -> dict[str, Any]:
        plan = self.planner.create_plan(task, step)
        plan.inputs["job_id"] = job_id
        dependency_outputs = {
            dependency: results_by_id[dependency]
            for dependency in step.depends_on
            if dependency in results_by_id
        }
        plan.inputs.dependency_outputs = dependency_outputs
        plan.inputs.previous_outputs = list(dependency_outputs.values())
        async with timed_stage(
            logger,
            f"{PipelineStage.SKILL}.{step.skill_name}",
            job_id=job_id,
            fields={
                "task_id": task.task_id,
                "step_id": step.step_id,
                "order": step.order,
                "legacy_stage": f"workflow.step.{step.skill_name}",
            },
        ):
            if step.skill_name == "search":
                result = await self.research_runner.run(task, step, plan, job_id=job_id)
            else:
                result = await self.executor.execute(plan)
        return {
            "step_id": step.step_id,
            "subtask_id": step.subtask_id,
            "skill_name": step.skill_name,
            "message": result.message,
            "data": result.data,
            "artifacts": result.artifacts,
        }

    @staticmethod
    def _is_search_only_workflow(task: StructuredTask, workflow: WorkflowPlan) -> bool:
        return (
            task.task_type == TaskType.SEARCH
            and bool(workflow.steps)
            and all(step.skill_name == "search" for step in workflow.steps)
        )

    @staticmethod
    def _normalize_workflow(task: StructuredTask, workflow: WorkflowPlan) -> WorkflowPlan:
        if workflow.mode != "workflow" or len(workflow.steps) <= 1:
            return workflow
        if task.task_type != TaskType.SEARCH:
            return workflow
        normalized_text = task.normalized_text.lower()
        doc_keywords = ("文档", "报告", "总结", "整理", "写", "生成", "draft", "doc")
        if not any(keyword in normalized_text for keyword in doc_keywords):
            workflow.steps = [workflow.steps[0]]
        return workflow

    @staticmethod
    def _inline_excel_creation_requested(task: StructuredTask) -> bool:
        if task.task_type != TaskType.EXCEL:
            return False
        source_text = task.source_text.strip()
        if "\n" not in source_text or not ("," in source_text or "\t" in source_text):
            return False
        request_text = f"{task.user_intent}\n{task.normalized_text}\n{source_text}".lower()
        return any(
            keyword in request_text
            for keyword in ("生成", "创建", "制作", "导出", "转成", "excel", "xlsx")
        )

    @classmethod
    def _fallback_inline_excel_workflow(cls, task: StructuredTask) -> WorkflowPlan | None:
        if not cls._inline_excel_creation_requested(task):
            return None
        return WorkflowPlan(
            mode="workflow",
            rationale="内联表格数据由 Excel 插件确定性写入，避免模型复述或改写源数据。",
            confidence=1.0,
            steps=[
                WorkflowStep(
                    order=1,
                    subtask_id="excel-create",
                    skill_name="excel",
                    skill_reason="用户要求把内联表格数据生成 Excel 文件。",
                    goal="按原始顺序和内容生成 Excel 工作簿。",
                    parameters={
                        "operation": "create",
                        "filename": "表格.xlsx",
                        "workbook_spec": {
                            "sheets": [
                                {
                                    "name": "数据",
                                    "rows": [],
                                    "freeze_panes": "A2",
                                    "autofilter": True,
                                }
                            ]
                        },
                    },
                )
            ],
        )

    _localize_search_date = staticmethod(ResearchRunner.localize_search_date)
