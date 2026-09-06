# -*- coding: utf-8 -*-
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from config.settings import settings
from app.services.timing import timed_stage

import logging


logger = logging.getLogger(__name__)


class SearchExecutor:
    base_url = "https://google.serper.dev"
    recency_filters = {
        "day": "qdr:d",
        "week": "qdr:w",
        "month": "qdr:m",
        "year": "qdr:y",
    }

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not settings.serper_key_id:
            raise RuntimeError("SERPER_KEY_ID is not configured.")

        parameters = inputs.get("parameters") if isinstance(inputs.get("parameters"), dict) else {}
        query = str(parameters.get("query") or inputs.get("text") or "").strip()
        if not query:
            raise ValueError("Search query is empty.")

        search_context = self._search_context(query, inputs)
        inferred_type = self._infer_search_type(search_context)
        requested_type = str(parameters.get("type") or inferred_type).lower()
        search_type = "news" if inferred_type == "news" else requested_type
        endpoint = "/news" if search_type == "news" else "/search"
        limit = self._normalize_limit(parameters.get("limit", 10))
        payload: dict[str, Any] = {"q": query, "num": limit}

        recency = self._normalize_recency(parameters.get("recency")) or self._infer_recency(search_context)
        if recency:
            payload["tbs"] = self.recency_filters[recency]

        if self._contains_cjk(query):
            payload.update({"gl": "cn", "hl": "zh-cn"})

        for key in ("gl", "hl", "num", "page", "autocorrect"):
            if key in parameters and parameters[key] is not None:
                payload[key] = parameters[key]

        async with timed_stage(
            logger,
            "provider.serper",
            job_id=str(inputs.get("job_id") or "") or None,
            fields={
                "task_id": inputs.get("task_id"),
                "step_id": (inputs.get("step") or {}).get("step_id")
                if isinstance(inputs.get("step"), dict)
                else None,
                "endpoint": endpoint,
                "query": query,
                "limit": limit,
            },
        ):
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.base_url}{endpoint}",
                    headers={
                        "X-API-KEY": settings.serper_key_id,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

        if response.status_code >= 400:
            raise RuntimeError(f"Serper request failed ({response.status_code}): {response.text[:500]}")

        raw = response.json()
        items = raw.get("news" if endpoint == "/news" else "organic", [])
        results = [self._normalize_result(item) for item in items[:limit]]
        return {
            "provider": "serper",
            "search_type": search_type,
            "query": query,
            "recency": recency,
            "time_filter": payload.get("tbs"),
            "retrieved_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "count": len(results),
            "results": results,
        }

    def _infer_search_type(self, query: str) -> str:
        news_keywords = ("新闻", "消息", "资讯", "最新", "news", "latest")
        return "news" if any(keyword in query.lower() for keyword in news_keywords) else "search"

    def _normalize_limit(self, value: Any) -> int:
        try:
            return max(1, min(int(value), 10))
        except (TypeError, ValueError):
            return 10

    def _normalize_recency(self, value: Any) -> str | None:
        normalized = str(value or "").strip().lower()
        aliases = {
            "d": "day",
            "1d": "day",
            "today": "day",
            "daily": "day",
            "w": "week",
            "1w": "week",
            "weekly": "week",
            "m": "month",
            "1m": "month",
            "monthly": "month",
            "y": "year",
            "1y": "year",
            "yearly": "year",
        }
        normalized = aliases.get(normalized, normalized)
        return normalized if normalized in self.recency_filters else None

    def _infer_recency(self, query: str) -> str | None:
        normalized = query.lower()
        if any(keyword in normalized for keyword in ("今天", "今日", "刚刚", "最新", "过去24小时", "today", "latest")):
            return "day"
        if any(keyword in normalized for keyword in ("本周", "近一周", "过去一周", "this week", "past week")):
            return "week"
        if any(keyword in normalized for keyword in ("本月", "近一个月", "过去一个月", "this month", "past month")):
            return "month"
        return None

    def _contains_cjk(self, value: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in value)

    def _search_context(self, query: str, inputs: dict[str, Any]) -> str:
        constraints = inputs.get("constraints")
        constraint_text = " ".join(str(item) for item in constraints) if isinstance(constraints, list) else ""
        return " ".join(
            part
            for part in (
                query,
                str(inputs.get("user_intent") or ""),
                constraint_text,
            )
            if part
        )

    def _normalize_result(self, item: dict[str, Any]) -> dict[str, Any]:
        # Serper's news response has used several aliases over time. Keep a
        # usable summary/date even when one of the preferred fields is absent.
        snippet = item.get("snippet") or item.get("description") or item.get("content") or item.get("text") or ""
        date = item.get("date") or item.get("published") or item.get("publishedAt") or item.get("timestamp") or ""
        source = item.get("source") or item.get("publisher") or item.get("domain") or ""
        if isinstance(source, dict):
            source = source.get("name") or source.get("title") or ""
        return {
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "snippet": str(snippet).strip(),
            "date": str(date).strip(),
            "source": str(source).strip(),
            "image_url": item.get("imageUrl", ""),
        }
