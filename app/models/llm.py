# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.domain.contracts import (
    ResearchAction,
    RouteDecision,
    StructuredTask,
    TaskExtraction,
    TaskType,
    WorkflowAssessment,
    WorkflowPlan,
    WorkflowStep,
)
from config.settings import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Qwen/DashScope-backed structured output client."""

    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )

    async def complete(self, prompt: str, **kwargs: Any) -> str:
        raise NotImplementedError("Use structured task and skill selection methods.")

    async def route_task(
        self,
        text: str,
        attachments: list[dict[str, Any]],
        skill_catalog: list[dict[str, str]],
    ) -> RouteDecision:
        """Identify the execution chain and select at most one skill."""
        return await asyncio.to_thread(self._route_task_sync, text, attachments, skill_catalog)

    async def analyze_tool_input(
        self,
        text: str,
        skill_name: str,
        attachments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Extract executable parameters after the intent router picked a skill."""
        return await asyncio.to_thread(
            self._analyze_tool_input_sync,
            text,
            skill_name,
            attachments,
        )

    def _route_task_sync(
        self,
        text: str,
        attachments: list[dict[str, Any]],
        skill_catalog: list[dict[str, str]],
    ) -> RouteDecision:
        skills_text = "\n".join(
            f"- {item.get('name', '')}: {item.get('description', '')}" for item in skill_catalog
        )
        attachment_names = [
            str(item.get("name") or item.get("file_name") or "attachment")
            for item in attachments
            if isinstance(item, dict)
        ]
        completion = self.client.chat.completions.create(
            model=settings.qwen_router_model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an intent router. Decide only whether the request is direct chat or needs a tool, "
                        "and for tool mode choose exactly one skill. Do not extract detailed tool parameters here. "
                        "Return only JSON with fields: mode, answer, skill_name, skill_reason, parameters, requires_summary. mode is direct or tool. "
                        "Use direct mode only when no skill is needed. For tool mode choose an exact skill "
                        "name from the catalog. For Excel attachments, choose operation csv_to_xlsx for .csv/.tsv, "
                        "inspect for .xlsx when the user asks to inspect, and edit only when the user asks to modify. "
                        "Keep parameters empty unless they are obvious file-routing metadata; never invent input_path. "
                        "Set requires_summary true only when the raw skill result needs a user-facing synthesis, "
                        "such as a search result; set it false for generated files and simple tool acknowledgements. "
                        "When selecting the search skill, the following tool-input analysis must plan three complementary "
                        "search dimensions from the user's complete current-turn request. "
                        "The answer must be Chinese when mode is direct."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Current date: {self._current_date()}\n"
                        f"Message: {text}\n"
                        f"Attachments: {json.dumps(attachment_names, ensure_ascii=False)}\n"
                        f"Available skills:\n{skills_text}"
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
        return self._parse_json_response(completion.choices[0].message.content, RouteDecision)

    def _analyze_tool_input_sync(
        self,
        text: str,
        skill_name: str,
        attachments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        attachment_names = [
            str(item.get("name") or item.get("file_name") or "attachment")
            for item in attachments
            if isinstance(item, dict)
        ]
        completion = self.client.chat.completions.create(
            model=settings.qwen_router_model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a tool input model. The intent router already selected the skill; "
                        "your only job is to extract executable parameters from the user's original request. "
                        "Return one JSON object with a single 'parameters' object. Do not return prose. "
                        "For Excel creation, operation must be create, filename must end with .xlsx, "
                        "workbook_spec.sheets must be a non-empty array, and every sheet.rows must be an array of row arrays. "
                        "Preserve CSV/TSV-like user data exactly in rows; do not replace rows with a count or description. "
                        "If the user asks for sample/arbitrary data, generate a small valid rows array. "
                        "For attachments, never invent input_path; the executor resolves downloaded files. "
                        "When Skill is search, use the complete original message as the planning subject and return "
                        "parameters.query plus planned_queries: an ordered array of exactly three objects with level, "
                        "purpose, and query. Level 1 is the direct core-intent query, level 2 covers complementary "
                        "entities and explicit constraints, and level 3 validates through an independent or alternative angle. "
                        "parameters.query must equal the first query. Preserve every explicit time, language, location, "
                        "and quantity constraint in all three queries; remove conversational and output-format wording."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Skill: {skill_name}\n"
                        f"Message: {text}\n"
                        f"Attachments: {json.dumps(attachment_names, ensure_ascii=False)}"
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
        try:
            payload = json.loads(completion.choices[0].message.content or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError("Tool input model returned invalid JSON.") from exc
        parameters = payload.get("parameters") if isinstance(payload, dict) else None
        if not isinstance(parameters, dict):
            raise RuntimeError("Tool input model must return a parameters object.")
        return parameters

    async def extract_task(self, text: str) -> TaskExtraction:
        return await asyncio.to_thread(self._extract_task_sync, text)

    async def plan_workflow(
        self,
        task: StructuredTask,
        skill_catalog: list[dict[str, str]],
    ) -> WorkflowPlan:
        return await asyncio.to_thread(self._plan_workflow_sync, task, skill_catalog)

    async def summarize_workflow_result(
        self,
        task: StructuredTask,
        workflow: WorkflowPlan,
        step_results: list[dict[str, Any]],
    ) -> WorkflowAssessment:
        return await asyncio.to_thread(self._summarize_workflow_result_sync, task, workflow, step_results)

    async def review_search_results(
        self,
        task: StructuredTask,
        step: WorkflowStep,
        attempts: list[dict[str, Any]],
        max_tool_calls: int,
    ) -> ResearchAction:
        return await asyncio.to_thread(
            self._review_search_results_sync,
            task,
            step,
            attempts,
            max_tool_calls,
        )

    async def translate_search_results(self, items: list[dict[str, Any]]) -> list[dict[str, str]]:
        return await asyncio.to_thread(self._translate_search_results_sync, items)

    def _extract_task_sync(self, text: str) -> TaskExtraction:
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "Extract a structured task from a Feishu message. "
                    "Return only a JSON object with these fields: "
                    "execution_mode, task_type, user_intent, normalized_text, entities, constraints, subtasks. "
                    "execution_mode must be either direct or workflow. "
                    "task_type must be one of: excel, ppt, copywriter, image, search, general. "
                    "entities and constraints must be JSON arrays of strings, never arrays of objects. "
                    "subtasks must be a JSON array of ordered subtasks, and each subtask must include "
                    "subtask_id, order, goal, task_type, normalized_text, dependencies, expected_output, hints. "
                    "dependencies and hints must also be JSON arrays of strings. "
                    "If the request can be answered without any tool, set execution_mode to direct and leave subtasks empty. "
                    "If the request needs tools or multiple steps, set execution_mode to workflow and split it into ordered subtasks. "
                    "For a pure search/news request, keep it to one search subtask. Do not invent cleanup/filter/format subtasks unless the user explicitly asks for them. "
                    "Resolve relative dates such as today, yesterday, and this week against the provided current date; never replace them with a guessed or stale year. "
                    "Only split into multiple subtasks when the user explicitly requests multiple phases, like search first and then write a document."
                ),
            },
            {
                "role": "user",
                "content": f"Current date: {self._current_date()}\nMessage: {text}",
            },
        ]
        last_error = ""
        for _ in range(2):
            if last_error:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The previous task JSON failed schema validation. "
                            "Return a corrected complete JSON object. "
                            f"Validation error: {last_error}"
                        ),
                    }
                )
            completion = self.client.chat.completions.create(
            model=settings.qwen_task_parser_model,
                temperature=0,
                messages=messages,
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content
            try:
                return self._parse_json_response(content, TaskExtraction)
            except RuntimeError as exc:
                last_error = str(exc)
                messages.append({"role": "assistant", "content": content or "{}"})
        raise RuntimeError(f"Task extraction failed schema validation after retry: {last_error}")

    def _plan_workflow_sync(
        self,
        task: StructuredTask,
        skill_catalog: list[dict[str, str]],
    ) -> WorkflowPlan:
        skills_text = "\n".join(
            f"- {item.get('name', '')}: {item.get('description', '')}" for item in skill_catalog
        )
        excel_source_context = ""
        if (
            task.task_type == TaskType.EXCEL
            and "\n" in task.source_text
            and ("," in task.source_text or "\t" in task.source_text)
        ):
            excel_source_context = (
                "\nInline CSV/TSV source data is available directly to the Excel executor. "
                "Do not repeat or translate its rows in workbook_spec. Use one create step, one sheet, "
                "and an empty rows array; the executor will inject the exact source rows before formatting. "
                "Do not add charts, formulas, summaries, or derived sheets unless the user explicitly requested them."
            )
        messages: list[dict[str, str]] = [
                {
                    "role": "system",
                    "content": (
                        "You are a workflow planner. "
                        "Break the request into ordered executable steps. "
                        "Return only a JSON object with these fields: mode, answer, rationale, confidence, subtasks, steps. "
                        "mode must be either direct or workflow. "
                        "If task.execution_mode is direct, always return direct mode and answer the user without tools. "
                        "Use direct mode only when no tool is needed. "
                        "For workflow mode, create one or more ordered steps that can be executed by skills. "
                        "Each step must include step_id, order, subtask_id, skill_name, skill_reason, goal, inputs, parameters, depends_on, expected_output. "
                        "depends_on must contain exact prior step_id values; use an empty array only when a step can run independently in parallel. "
                        "Choose skill_name from the provided skill catalog by exact name. "
                        "Prefer search for search/research work, copywriter for drafting and rewriting, excel for tables and spreadsheets, ppt for presentations, and image for visual generation. "
                        "For an excel step, parameters.operation must be one of create, inspect, edit, csv_to_xlsx, or xlsx_to_csv. "
                        "For create, parameters must include filename ending in .xlsx and workbook_spec with a non-empty sheets array. "
                        "A new workbook must be completed in exactly one excel create step; include formulas, formatting, tables, and charts in that same workbook_spec. Do not follow create with excel edit steps. "
                        "Each workbook_spec sheet may include name, rows, cells, column_widths, row_heights, merges, freeze_panes, autofilter, conditional_formats, validations, tables, and charts. "
                        "sheet.rows must always be a JSON array of row arrays containing the actual values to write, never an integer row count. sheet.cells must be a JSON object keyed by A1 references. "
                        "A chart supports only type bar, line, or pie and uses title, data, categories, anchor, and titles_from_data. "
                        "A cell object may include value or formula plus type, format, bold, italic, font_name, font_size, font_color, fill, border, align, valign, wrap, hyperlink, or note. "
                        "Use typed JSON numbers, booleans, and ISO dates instead of formatted strings. Derived spreadsheet values must be formulas, and formulas must reference cells rather than embedding unexplained constants. "
                        "For edit, use parameters.sheet_name, parameters.sets, and parameters.append_rows; sets maps A1 or 'Sheet Name'!A1 references to scalar or cell objects. "
                        "Edit does not add charts or tables. Use edit only when modifying an existing attachment, never to finish a newly created workbook. "
                        "For inspect or conversion, do not invent input_path when the task has an attachment; the executor will use the downloaded attachment. "
                        "Create professional, readable workbooks with useful headers, sensible widths, freeze panes, number formats, and charts only when they improve the requested result. "
                        "If the request contains multiple actions, map them to multiple steps in sequence. "
                        "For a pure search/news request, use exactly one search step. Do not invent cleanup/filter/format steps unless the user explicitly requests them. "
                        "For every search step, treat the user's complete current-turn request as the sole planning subject and rewrite it into concise search-engine keywords: remove requested counts, output formatting, and conversational wording. "
                        "Search step parameters must include query, planned_queries, type, recency, limit, gl, and hl. "
                        "planned_queries must be an ordered JSON array of exactly three objects, each with level (1, 2, or 3), purpose, and query. Level 1 targets the direct core intent; level 2 covers complementary entities and explicit constraints; level 3 validates the answer through an independent or alternative angle. "
                        "parameters.query must equal planned_queries[0].query. Keep all explicit time, language, location, and quantity constraints across all three queries, and never invent requirements. "
                        "type must be news for news requests. recency must be day for today/latest news, week for this-week requests, month for this-month requests, or null when the user gave no freshness constraint. "
                        "For broad technology news, use topic keywords such as AI, chips, semiconductors, large models, robotics, or other topics implied by the request instead of searching the full user sentence. "
                        "Preserve only constraints stated by the user. Do not add authority, originality, preferred publishers, or stricter freshness requirements. "
                        "Use the provided subtasks as the source of truth for user intent. "
                        "If the request asks to search information and then produce a document, plan search first and then a writing step. "
                        "If mode is direct, answer must contain the final user-facing reply in Chinese and steps must be empty. "
                        "confidence must be a number from 0 to 1."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Task type: {task.task_type.value}\n"
                        f"Intent: {task.user_intent}\n"
                        f"Text: {task.normalized_text}\n"
                        f"Current date: {self._current_date()}\n"
                        f"Subtasks: {json.dumps([subtask.model_dump() for subtask in task.subtasks], ensure_ascii=False)}\n"
                        f"Available skills:\n{skills_text}"
                        f"{excel_source_context}"
                    ),
                },
            ]
        last_error = ""
        for _ in range(2):
            if last_error:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The workflow failed executable schema validation: "
                            f"{last_error}. Return a corrected complete JSON workflow."
                        ),
                    }
                )
            completion = self.client.chat.completions.create(
                model=settings.qwen_agent_model,
                temperature=0,
                messages=messages,
                response_format={"type": "json_object"},
            )
            try:
                workflow = self._parse_json_response(completion.choices[0].message.content, WorkflowPlan)
                last_error = self._validate_workflow_plan(workflow)
                if not last_error:
                    return workflow
            except RuntimeError as exc:
                last_error = str(exc)
            messages.append(
                {
                    "role": "assistant",
                    "content": completion.choices[0].message.content or "{}",
                }
            )
        raise RuntimeError(f"Workflow planning failed executable schema validation: {last_error}")

    def _validate_workflow_plan(self, workflow: WorkflowPlan) -> str:
        excel_steps = [step for step in workflow.steps if step.skill_name == "excel"]
        create_steps = [step for step in excel_steps if step.parameters.get("operation") == "create"]
        if create_steps and len(excel_steps) != 1:
            return "a new workbook must use exactly one excel create step"
        for step in excel_steps:
            parameters = step.parameters
            operation = str(parameters.get("operation") or "")
            if operation not in {"create", "inspect", "edit", "csv_to_xlsx", "xlsx_to_csv"}:
                return f"unsupported excel operation: {operation or 'missing'}"
            if operation == "create":
                filename = str(parameters.get("filename") or "")
                spec = parameters.get("workbook_spec")
                if not filename.lower().endswith(".xlsx"):
                    return "excel create filename must end in .xlsx"
                if not isinstance(spec, dict) or not isinstance(spec.get("sheets"), list) or not spec["sheets"]:
                    return "excel create requires a non-empty workbook_spec.sheets array"
                for sheet in spec["sheets"]:
                    if not isinstance(sheet, dict):
                        return "each excel sheet must be an object"
                    if not isinstance(sheet.get("rows", []), list):
                        return "excel sheet.rows must be an array of row arrays, not a row count"
                    if not all(isinstance(row, list) for row in sheet.get("rows", [])):
                        return "every excel sheet row must be an array"
                    if not isinstance(sheet.get("cells", {}), dict):
                        return "excel sheet.cells must be an object keyed by A1 references"
                    charts = sheet.get("charts", [])
                    if not isinstance(charts, list):
                        return "excel sheet.charts must be an array"
                    if any(not isinstance(chart, dict) or chart.get("type", "bar") not in {"bar", "line", "pie"} or not chart.get("data") for chart in charts):
                        return "each excel chart requires data and type bar, line, or pie"
            if operation == "edit":
                if "charts" in parameters or "tables" in parameters:
                    return "excel edit supports sets and append_rows only; chart and table changes belong in create"
                if not isinstance(parameters.get("sets", {}), dict) or not isinstance(parameters.get("append_rows", []), list):
                    return "excel edit sets must be an object and append_rows must be an array"
        for step in workflow.steps:
            if step.skill_name != "search":
                continue
            planned = step.parameters.get("planned_queries")
            if not isinstance(planned, list) or len(planned) != 3:
                return "search steps require exactly three planned_queries"
            queries: list[str] = []
            for index, item in enumerate(planned, start=1):
                if not isinstance(item, dict):
                    return f"search planned_queries[{index}] must be an object"
                level = item.get("level")
                query = str(item.get("query") or "").strip()
                purpose = str(item.get("purpose") or "").strip()
                if level != index or not purpose or not query:
                    return f"search planned_queries[{index}] requires level, purpose, and query"
                queries.append(query.casefold())
            if len(set(queries)) != 3:
                return "search planned_queries must contain distinct queries"
            if str(step.parameters.get("query") or "").strip().casefold() != queries[0]:
                return "search parameters.query must equal planned_queries[0].query"
        return ""

    def _review_search_results_sync(
        self,
        task: StructuredTask,
        step: WorkflowStep,
        attempts: list[dict[str, Any]],
        max_tool_calls: int,
    ) -> ResearchAction:
        completion = self.client.chat.completions.create(
            model=settings.qwen_agent_model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the research supervisor in an iterative open-source-style deep research loop. "
                        "Inspect all search attempts against the user's exact request before deciding the next action. "
                        "Return only a JSON object with fields: type, reason, arguments, accepted_urls. "
                        "type must be tool_call or complete. "
                         "Use complete when the collected attempts have enough unique, topically relevant results to satisfy the requested count, "
                         "but do not reject a usable result solely because the provider gives a relative date or an empty snippet. "
                         "accepted_urls should include every usable URL you approve across every attempt; the program will merge all attempts and fill the requested count. "
                        "Treat syndicated coverage of the same underlying event as one result even when URLs and headlines differ. "
                        "Reject off-topic results and do not count them toward completion. "
                        "Otherwise return tool_call with a new, non-duplicate focused query in arguments.query. "
                        "For tool_call, arguments must also include type, recency, limit, gl, and hl. "
                        "When the step includes planned_queries, execute those three levels in order before using any "
                        "supervisor-generated fallback query; do not stop early merely because one level has enough URLs. "
                         "Never broaden a time constraint merely to fill the requested count, but continue searching within the same window when the count is still short. "
                        "Change topic keywords or language when prior searches are irrelevant. "
                        "Do not repeat a previous query. When the tool-call budget is exhausted, return complete and explain the remaining gap in reason."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "current_date": self._current_date(),
                            "request": task.normalized_text,
                            "intent": task.user_intent,
                            "constraints": task.constraints,
                            "step": step.model_dump(),
                            "tool_calls_used": len(attempts),
                            "max_tool_calls": max_tool_calls,
                            "attempts": attempts,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
        return self._parse_json_response(
            completion.choices[0].message.content,
            ResearchAction,
        )

    def _summarize_workflow_result_sync(
        self,
        task: StructuredTask,
        workflow: WorkflowPlan,
        step_results: list[dict[str, Any]],
    ) -> WorkflowAssessment:
        messages: list[dict[str, str]] = [
            {
                    "role": "system",
                    "content": (
                        "You are the final response judge for a tool-using assistant. "
                        "First compare the user's original intent and constraints with the actual workflow results, "
                        "then write the final user-facing reply in Chinese. "
                        "Return only a JSON object with these fields: "
                        "intent_satisfied, rationale, answer, missing_information. "
                        "intent_satisfied must reflect whether the results actually satisfy the request. "
                        "rationale is an internal concise judgment and must not be repeated mechanically in answer. "
                        "missing_information must be a JSON array. "
                        "Use the provided workflow execution results as the source of truth. "
                        "Apply only constraints explicitly present in the user's request or structured task; do not invent authority, originality, or stricter time requirements. "
                        "Never copy a skill's status message as the final answer and do not expose raw JSON, "
                        "workflow internals, skill names, prompts, or diagnostic text. "
                         "If the task is a search task, produce a Chinese news digest with exactly the requested number when enough valid results exist: a clear title plus numbered items, each with a short Chinese headline, source name and URL, time, and a brief summary. "
                         "Translate or paraphrase English titles and English summaries into natural Chinese; never copy English snippets verbatim when writing the final answer. "
                         "Do not say you cannot find results when the provided step results already contain items. Do not claim fewer items when the step data contains enough usable results. "
                         "For news, a provider relative date such as '2 hours ago' is acceptable unless the user explicitly requested an exact timestamp; an empty provider snippet is not by itself a reason to reject an otherwise relevant item. "
                        "If the results only partially satisfy the request, still summarize the useful results, clearly state the gap, and set intent_satisfied to false. "
                        "If the task is document-generation or multi-step work, summarize the final artifact or draft in Chinese. "
                        "When an Excel result contains a verified file artifact, state that the workbook is complete and attached, briefly summarize its sheets or contents, and do not expose its local filesystem path. "
                        "Keep the tone crisp, useful, and news-like."
                    ),
            },
            {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": task.model_dump(),
                            "workflow": workflow.model_dump(),
                            "step_results": step_results,
                        },
                        ensure_ascii=False,
                    ),
            },
        ]
        last_error = ""
        for _ in range(2):
            if last_error:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The draft failed final quality validation: "
                            f"{last_error}. Return a corrected complete JSON response."
                        ),
                    }
                )
            completion = self.client.chat.completions.create(
                model=settings.qwen_agent_model,
                temperature=0,
                messages=messages,
                response_format={"type": "json_object"},
            )
            assessment = self._parse_json_response(
                completion.choices[0].message.content,
                WorkflowAssessment,
            )
            last_error = self._validate_final_assessment(task, step_results, assessment)
            if not last_error:
                return assessment
            messages.append(
                {
                    "role": "assistant",
                    "content": completion.choices[0].message.content or "{}",
                }
            )
        raise RuntimeError(f"Final response failed quality validation: {last_error}")

    def _translate_search_results_sync(self, items: list[dict[str, Any]]) -> list[dict[str, str]]:
        translated: list[dict[str, str]] = []
        for start in range(0, len(items), 5):
            batch = items[start:start + 5]
            try:
                translated.extend(self._translate_search_batch_sync(batch))
            except RuntimeError:
                for item in batch:
                    translated.extend(self._translate_search_batch_sync([item]))
        return translated

    def _translate_search_batch_sync(self, items: list[dict[str, Any]]) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are a Chinese news editor. Rewrite every provided title as a natural Chinese headline "
                    "and write a concise Chinese summary based only on the provided title and summary. "
                    "Do not merely copy or translate word for word; summarize the reported event without adding facts. "
                    "Proper nouns may remain in their original language, but every title and every summary must contain Chinese characters. "
                    "Return only a JSON object with an items array in the original order and with exactly the same length. "
                    "Each output item must contain only title and summary."
                ),
            },
            {"role": "user", "content": json.dumps(items, ensure_ascii=False)},
        ]
        last_error = ""
        for _ in range(2):
            if last_error:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The previous output was invalid or not fully Chinese. "
                            "Return the complete corrected JSON object. "
                            f"Validation error: {last_error}"
                        ),
                    }
                )
            try:
                completion = self.client.chat.completions.create(
                    model=settings.qwen_translator_model,
                    temperature=0,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
            except Exception as exc:
                # DashScope may hide small models behind account/region access
                # controls. Keep news delivery working while making the cause
                # explicit; once access is enabled, the preferred model is
                # used automatically again.
                if "model_not_found" not in str(exc) and "does not exist" not in str(exc):
                    raise
                logger.warning(
                    "Translator model %s unavailable; falling back to %s: %s",
                    settings.qwen_translator_model,
                    settings.qwen_agent_model,
                    exc,
                )
                completion = self.client.chat.completions.create(
                    model=settings.qwen_agent_model,
                    temperature=0,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
            content = completion.choices[0].message.content or "{}"
            try:
                payload = json.loads(content)
                translated = payload.get("items") if isinstance(payload, dict) else payload
                normalized = self._normalize_chinese_search_batch(translated, len(items))
                return normalized
            except (json.JSONDecodeError, RuntimeError) as exc:
                last_error = str(exc)
                messages.append({"role": "assistant", "content": content})
        raise RuntimeError(f"Chinese news summarization failed after retry: {last_error}")

    def _normalize_chinese_search_batch(self, value: Any, expected_count: int) -> list[dict[str, str]]:
        if not isinstance(value, list) or len(value) != expected_count:
            raise RuntimeError("Qwen returned an invalid Chinese news item count.")
        normalized: list[dict[str, str]] = []
        for item in value:
            if not isinstance(item, dict):
                raise RuntimeError("Qwen returned an invalid Chinese news item.")
            title = str(item.get("title") or "").strip()
            summary = str(item.get("summary") or "").strip()
            if not title or not summary:
                raise RuntimeError("Chinese news title and summary are required.")
            if not re.search(r"[\u4e00-\u9fff]", title) or not re.search(r"[\u4e00-\u9fff]", summary):
                raise RuntimeError("Chinese news title and summary must contain Chinese characters.")
            normalized.append({"title": title, "summary": summary})
        return normalized

    def _parse_json_response(self, content: str | None, schema: type[BaseModel]) -> Any:
        if not content:
            raise RuntimeError("Qwen returned an empty response.")
        try:
            payload = json.loads(content)
            payload = self._normalize_payload(payload, schema)
            return schema.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError(f"Qwen returned invalid structured data: {content}") from exc

    def _normalize_payload(self, payload: Any, schema: type[BaseModel]) -> Any:
        if schema is TaskExtraction and isinstance(payload, dict):
            mode = str(payload.get("execution_mode") or "workflow").lower()
            payload["execution_mode"] = "direct" if mode == "direct" else "workflow"
            for key in ("entities", "constraints"):
                payload[key] = self._normalize_text_list(payload.get(key))
            subtasks = payload.get("subtasks")
            if subtasks is None:
                payload["subtasks"] = []
            elif isinstance(subtasks, dict):
                payload["subtasks"] = [subtasks]
            elif not isinstance(subtasks, list):
                payload["subtasks"] = [subtasks]
            normalized_subtasks = []
            for index, subtask in enumerate(payload["subtasks"], start=1):
                if not isinstance(subtask, dict):
                    continue
                for key in ("dependencies", "hints"):
                    subtask[key] = self._normalize_text_list(subtask.get(key))
                if not subtask.get("order"):
                    subtask["order"] = index
                normalized_subtasks.append(subtask)
            payload["subtasks"] = normalized_subtasks
        if schema is WorkflowPlan and isinstance(payload, dict):
            if payload.get("mode") == "direct":
                payload["steps"] = []
                payload["subtasks"] = []
            if payload.get("mode") not in {"direct", "workflow"}:
                payload["mode"] = "workflow"
            if not isinstance(payload.get("steps"), list):
                payload["steps"] = []
            if not isinstance(payload.get("subtasks"), list):
                payload["subtasks"] = []
            normalized_steps = []
            for index, step in enumerate(payload["steps"], start=1):
                if not isinstance(step, dict):
                    continue
                if not step.get("step_id"):
                    step["step_id"] = f"step-{index}"
                if not step.get("subtask_id"):
                    step["subtask_id"] = f"subtask-{index}"
                for key in ("inputs", "parameters", "depends_on"):
                    value = step.get(key)
                    if value is None:
                        step[key] = {} if key in ("inputs", "parameters") else []
                    elif key in ("inputs", "parameters") and not isinstance(value, dict):
                        step[key] = {}
                    elif key == "depends_on" and not isinstance(value, list):
                        step[key] = [value]
                if not step.get("order"):
                    step["order"] = index
                normalized_steps.append(step)
            payload["steps"] = normalized_steps
        return payload

    def _normalize_text_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, dict):
            preferred = next(
                (
                    value.get(key)
                    for key in ("value", "text", "name", "description", "constraint", "hint", "span")
                    if value.get(key) not in (None, "")
                ),
                None,
            )
            items = [preferred] if preferred is not None else list(value.values())
        elif isinstance(value, (list, tuple, set)):
            items = list(value)
        else:
            items = [value]

        normalized: list[str] = []
        for item in items:
            if isinstance(item, (dict, list, tuple, set)):
                nested = self._normalize_text_list(item)
                for text in nested:
                    if text not in normalized:
                        normalized.append(text)
                continue
            text = str(item).strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    def _current_date(self) -> str:
        return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()

    def _validate_final_assessment(
        self,
        task: StructuredTask,
        step_results: list[dict[str, Any]],
        assessment: WorkflowAssessment,
    ) -> str:
        if task.task_type != TaskType.SEARCH:
            return ""
        has_search_results = any(
            isinstance(step.get("data"), dict) and step["data"].get("results")
            for step in step_results
        )
        if has_search_results and not re.search(r"https?://", assessment.answer):
            return "each search item must include its source URL"
        return ""
