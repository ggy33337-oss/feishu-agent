# -*- coding: utf-8 -*-
import json
import logging
import re
from typing import Any

from app.core.ports.llm import TaskExtractor, TaskRouter
from app.domain.contracts import RouteDecision, StructuredTask, TaskExtraction, TaskSubtask, TaskType
from app.models.llm import LLMClient
from app.core.orchestrator.stages import PipelineStage
from app.services.timing import timed_stage

logger = logging.getLogger(__name__)


class TaskParser:
    """Convert Feishu webhook payloads into structured tasks using an LLM."""

    def __init__(
        self,
        llm: TaskExtractor | TaskRouter | None = None,
        skill_catalog: list[dict[str, str]] | None = None,
    ) -> None:
        self.llm = llm or LLMClient()
        self.skill_catalog = skill_catalog or []

    async def parse(self, payload: dict[str, Any], job_id: str | None = None) -> StructuredTask:
        event = payload.get("event", payload)
        message = event.get("message", {})
        sender = event.get("sender", {})
        sender_type = sender.get("sender_type") if isinstance(sender, dict) else None
        if sender_type and sender_type != "user":
            raise ValueError("Ignored non-user message.")

        text = self._extract_text(message)
        if not text:
            raise ValueError("No message text found in Feishu payload.")

        attachments = self._extract_attachments(message)
        route_task = getattr(self.llm, "route_task", None)
        if callable(route_task) and self.skill_catalog:
            try:
                async with timed_stage(
                    logger,
                    PipelineStage.INTENT_ROUTER,
                    job_id=job_id,
                    fields={"attachment_count": len(attachments)},
                ):
                    route = await route_task(text, attachments, self.skill_catalog)
            except RuntimeError:
                route = self._fallback_route(text, attachments)
                if route is None:
                    raise
                logger.warning("Routing failed; using deterministic fallback for: %s", text)
            analyze_tool_input = getattr(self.llm, "analyze_tool_input", None)
            if route.mode == "tool" and callable(analyze_tool_input):
                try:
                    async with timed_stage(
                        logger,
                        PipelineStage.TOOL_ANALYZE,
                        job_id=job_id,
                        fields={"skill_name": route.skill_name, "attachment_count": len(attachments)},
                    ):
                        analyzed_parameters = await analyze_tool_input(
                            text,
                            str(route.skill_name or ""),
                            attachments,
                        )
                    route.parameters = analyzed_parameters
                except RuntimeError:
                    logger.warning(
                        "Tool input analysis failed; using router parameters for %s",
                        route.skill_name,
                    )
            return self._build_routed_task(payload, text, sender, message, route, attachments)

        try:
            async with timed_stage(logger, PipelineStage.INTENT_ROUTER, job_id=job_id):
                extracted = await self.llm.extract_task(text)  # type: ignore[attr-defined]
        except RuntimeError:
            extracted = self._fallback_search_extraction(text)
            if extracted is None:
                raise
            logger.warning("Task extraction failed; using deterministic search fallback for: %s", text)
        if extracted.execution_mode == "workflow" and not extracted.subtasks:
            extracted.subtasks = [
                TaskSubtask(
                    order=1,
                    goal=extracted.user_intent,
                    task_type=extracted.task_type,
                    normalized_text=extracted.normalized_text,
                )
            ]
        return StructuredTask(
            task_type=extracted.task_type,
            user_intent=extracted.user_intent,
            normalized_text=extracted.normalized_text,
            source_text=text,
            execution_mode=extracted.execution_mode,
            user_id=self._nested_get(sender, "sender_id", "open_id"),
            chat_id=message.get("chat_id"),
            message_id=message.get("message_id"),
            reply_token=event.get("reply_token"),
            attachments=attachments,
            entities=extracted.entities,
            constraints=extracted.constraints,
            subtasks=extracted.subtasks,
            raw=payload,
        )

    def _build_routed_task(
        self,
        payload: dict[str, Any],
        text: str,
        sender: dict[str, Any],
        message: dict[str, Any],
        route: RouteDecision,
        attachments: list[dict[str, Any]],
    ) -> StructuredTask:
        if route.mode == "direct":
            task_type = TaskType.GENERAL
            subtasks: list[TaskSubtask] = []
        else:
            skill_name = str(route.skill_name or "general")
            try:
                task_type = TaskType(skill_name)
            except ValueError:
                task_type = TaskType.GENERAL
            subtasks = [
                TaskSubtask(
                    order=1,
                    goal=text,
                    task_type=task_type,
                    normalized_text=text,
                )
            ]
        parameters = dict(route.parameters)
        self._apply_attachment_route(parameters, route, attachments)
        if route.skill_name == "search":
            self._ensure_search_plan(parameters, text)
        if route.skill_name == "excel":
            parameters = self._normalize_excel_parameters(parameters, text)
        if route.mode == "direct":
            route.skill_name = None
        elif route.skill_name:
            try:
                task_type = TaskType(route.skill_name)
            except ValueError:
                task_type = TaskType.GENERAL
        return StructuredTask(
            task_type=task_type,
            user_intent=text,
            normalized_text=text,
            source_text=text,
            execution_mode="direct" if route.mode == "direct" else "workflow",
            user_id=self._nested_get(sender, "sender_id", "open_id"),
            chat_id=message.get("chat_id"),
            message_id=message.get("message_id"),
            reply_token=payload.get("event", {}).get("reply_token") if isinstance(payload.get("event"), dict) else None,
            attachments=attachments,
            subtasks=subtasks,
            raw=payload,
            route_skill=route.skill_name,
            route_parameters=parameters,
            route_answer=route.answer,
            route_reason=route.skill_reason,
            route_requires_summary=route.requires_summary,
        )

    @staticmethod
    def _ensure_search_plan(parameters: dict[str, Any], text: str) -> None:
        """Provide a deterministic three-angle plan when model analysis is unavailable."""
        planned = parameters.get("planned_queries")
        normalized_queries: list[tuple[str, str]] = []
        seen: set[str] = set()
        if isinstance(planned, list):
            for item in planned:
                if isinstance(item, dict):
                    query = str(item.get("query") or "").strip()
                    purpose = str(item.get("purpose") or "").strip()
                else:
                    query = str(item or "").strip()
                    purpose = ""
                key = query.casefold()
                if query and key not in seen:
                    seen.add(key)
                    normalized_queries.append((query, purpose))
                if len(normalized_queries) == 3:
                    break

        base = TaskParser._clean_search_query(
            normalized_queries[0][0] if normalized_queries else str(parameters.get("query") or text)
        ) or text.strip()
        defaults = (
            ("核心意图", base),
            ("实体与约束补充", f"{base} 关键实体 相关信息"),
            ("独立角度交叉验证", f"{base} 来源 对比 核实"),
        )
        queries: list[dict[str, Any]] = []
        used: set[str] = set()
        for level, (default_purpose, default_query) in enumerate(defaults, start=1):
            candidate = normalized_queries[level - 1][0] if level <= len(normalized_queries) else default_query
            candidate = TaskParser._clean_search_query(candidate) or default_query
            key = candidate.casefold()
            if key in used:
                candidate = default_query
                key = candidate.casefold()
            if key in used:
                candidate = f"{default_query} 角度{level}"
                key = candidate.casefold()
            used.add(key)
            queries.append(
                {
                    "level": level,
                    "purpose": normalized_queries[level - 1][1] or default_purpose
                    if level <= len(normalized_queries)
                    else default_purpose,
                    "query": candidate,
                }
            )
        parameters["query"] = queries[0]["query"]
        parameters["planned_queries"] = queries

    @staticmethod
    def _clean_search_query(value: str) -> str:
        cleaned = re.sub(r"\d+\s*条", "", str(value or ""))
        cleaned = re.sub(r"^(?:请|帮我)?\s*(?:搜索|检索|查找|搜一下|查一下)\s*", "", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def _apply_attachment_route(
        parameters: dict[str, Any],
        route: RouteDecision,
        attachments: list[dict[str, Any]],
    ) -> None:
        if not attachments:
            if route.skill_name == "search":
                parameters.setdefault("query", "")
                parameters.setdefault("type", "news" if "新闻" in str(route.skill_reason) else "search")
            return
        name = str(attachments[0].get("name") or attachments[0].get("file_name") or "").lower()
        if not name.endswith((".csv", ".tsv")):
            if name.endswith(".xlsx") and not parameters.get("operation"):
                parameters["operation"] = "inspect"
            return
        # File type is deterministic; do not let a model send CSV to openpyxl.
        route.skill_name = "excel"
        parameters["operation"] = "csv_to_xlsx"
        if not str(parameters.get("filename") or "").lower().endswith(".xlsx"):
            stem = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0]
            parameters["filename"] = f"{stem or 'converted'}.xlsx"

    def _fallback_route(
        self,
        text: str,
        attachments: list[dict[str, Any]],
    ) -> RouteDecision | None:
        if attachments:
            parameters: dict[str, Any] = {}
            route = RouteDecision(
                mode="tool",
                skill_name="excel",
                skill_reason="附件处理由文件类型确定。",
                parameters=parameters,
            )
            self._apply_attachment_route(parameters, route, attachments)
            if not parameters:
                parameters["operation"] = "inspect"
            return route
        if self._looks_like_excel_creation(text):
            return RouteDecision(
                mode="tool",
                skill_name="excel",
                skill_reason="意图模型不可用时，按明确 Excel 创建请求执行确定性兜底。",
                parameters=self._normalize_excel_parameters({}, text),
                requires_summary=False,
            )
        search = self._fallback_search_extraction(text)
        if search is None:
            return None
        return RouteDecision(
            mode="tool",
            skill_name="search",
            skill_reason="根据消息关键词执行搜索。",
            parameters={"query": search.normalized_text, "type": "news" if "新闻" in text else "search"},
            requires_summary=True,
        )

    @staticmethod
    def _looks_like_excel_creation(text: str) -> bool:
        normalized = text.lower()
        excel_terms = ("excel", "xlsx", "表格", "工作簿", "电子表格")
        create_terms = ("生成", "创建", "制作", "导出", "随便填", "填充", "样例", "示例")
        return (
            any(term in normalized for term in excel_terms)
            or "数据随便填" in normalized
        ) and any(term in normalized for term in create_terms)

    @classmethod
    def _normalize_excel_parameters(
        cls,
        parameters: dict[str, Any],
        source_text: str = "",
    ) -> dict[str, Any]:
        """Make model-produced create parameters executable and deterministic."""
        normalized = dict(parameters)
        operation = str(normalized.get("operation") or "create").strip().lower()
        inline_rows = cls._parse_inline_rows(source_text)
        if operation == "csv_to_xlsx" and inline_rows:
            # csv_to_xlsx requires a downloaded file. Inline CSV/TSV text is
            # already the source file, so convert it into a workbook create.
            normalized["operation"] = "create"
            normalized["workbook_spec"] = {
                "sheets": [{"name": "数据", "rows": inline_rows, "freeze_panes": "A2", "autofilter": True}]
            }
            operation = "create"
        if operation != "create":
            return normalized
        normalized["operation"] = "create"
        filename = str(normalized.get("filename") or "示例表格.xlsx")
        normalized["filename"] = filename if filename.lower().endswith(".xlsx") else f"{filename}.xlsx"
        spec = normalized.get("workbook_spec")
        if not isinstance(spec, dict):
            spec = {}
        sheets = spec.get("sheets")
        if not isinstance(sheets, list) or not sheets:
            sheets = [{}]
        source_rows = inline_rows
        fallback_rows = source_rows or [
            ["项目", "数量", "单价", "金额"],
            ["A", 10, 25, ""],
            ["B", 5, 40, ""],
            ["C", 8, 15, ""],
            ["合计", "", "", ""],
        ]
        normalized_sheets: list[dict[str, Any]] = []
        for index, raw_sheet in enumerate(sheets, start=1):
            sheet = dict(raw_sheet) if isinstance(raw_sheet, dict) else {}
            rows = sheet.get("rows")
            valid_rows = rows if isinstance(rows, list) and all(isinstance(row, list) for row in rows) else []
            sheet["rows"] = valid_rows or fallback_rows
            if not isinstance(sheet.get("cells"), dict):
                sheet["cells"] = {}
            sheet.setdefault("name", "数据" if index == 1 else f"数据{index}")
            sheet.setdefault("freeze_panes", "A2")
            sheet.setdefault("autofilter", True)
            normalized_sheets.append(sheet)
        spec["sheets"] = normalized_sheets
        normalized["workbook_spec"] = spec
        return normalized

    @staticmethod
    def _parse_inline_rows(source_text: str) -> list[list[str]]:
        rows: list[list[str]] = []
        for line in source_text.splitlines():
            value = line.strip()
            if not value or ("," not in value and "\t" not in value):
                continue
            delimiter = "\t" if "\t" in value and "," not in value else ","
            row = [item.strip() for item in value.split(delimiter)]
            if len(row) >= 2:
                rows.append(row)
        return rows

    def _fallback_search_extraction(self, text: str) -> TaskExtraction | None:
        cleaned = re.sub(r"@_user_\d+\s*", "", text).strip()
        search_keywords = ("新闻", "资讯", "搜索", "检索", "查找", "搜一下", "查一下", "news", "search")
        if not cleaned or not any(keyword in cleaned.lower() for keyword in search_keywords):
            return None

        constraints: list[str] = []
        count_match = re.search(r"(\d+)\s*条", cleaned)
        if count_match:
            constraints.append(f"数量：{count_match.group(1)}条")
        for keyword in ("今天", "今日", "昨天", "昨日", "本周", "本月", "最新"):
            if keyword in cleaned:
                constraints.append(f"时间：{keyword}")
                break
        return TaskExtraction(
            execution_mode="workflow",
            task_type=TaskType.SEARCH,
            user_intent=cleaned,
            normalized_text=cleaned,
            entities=[cleaned],
            constraints=constraints,
        )

    def _extract_text(self, message: dict[str, Any]) -> str:
        content = self._parse_content(message.get("content"))
        if isinstance(content, dict):
            text = self._extract_rich_text(content).strip()
            if text:
                return text
            file_name = str(content.get("file_name") or "").strip()
            if content.get("file_key"):
                return f"请处理 Excel 文件：{file_name or '附件'}"
        if isinstance(content, str):
            return content.strip()
        return str(message.get("text", "")).strip()

    def _extract_rich_text(self, value: Any) -> str:
        """Extract text from plain, post, and rich-text message payloads."""
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, list):
            parts = [self._extract_rich_text(item) for item in value]
            parts = [part for part in parts if part]
            if not parts:
                return ""
            # Feishu represents paragraphs as nested lists and inline spans as
            # a flat list. Preserve paragraph breaks without splitting spans.
            separator = "\n" if any(isinstance(item, list) for item in value) else ""
            return separator.join(parts)
        if not isinstance(value, dict):
            return ""

        direct_text = value.get("text")
        if isinstance(direct_text, (str, int, float)):
            return str(direct_text)
        if value.get("tag") == "at":
            return str(value.get("user_name") or "").strip()

        for key in ("content", "zh_cn", "en_us", "ja_jp"):
            if key in value:
                text = self._extract_rich_text(value[key])
                if text:
                    return text

        ignored_keys = {"file_key", "file_name", "tag", "style", "id", "type"}
        parts = [
            self._extract_rich_text(nested)
            for key, nested in value.items()
            if key not in ignored_keys
        ]
        parts = [part for part in parts if part]
        return "\n".join(parts)

    def _extract_attachments(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        attachments = [
            dict(item)
            for item in message.get("attachments", [])
            if isinstance(item, dict)
        ]
        content = self._parse_content(message.get("content"))
        if isinstance(content, dict) and content.get("file_key"):
            attachments.append(
                {
                    "type": "file",
                    "file_key": str(content["file_key"]),
                    "name": str(content.get("file_name") or "attachment.xlsx"),
                }
            )
        return attachments

    def _parse_content(self, content: Any) -> Any:
        if not isinstance(content, str):
            return content
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content

    def _nested_get(self, data: dict[str, Any], *keys: str) -> Any:
        current: Any = data
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current
