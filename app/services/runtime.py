# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.core.orchestrator.agent import Agent
from app.core.orchestrator.executor import Executor
from app.core.parser.task_parser import TaskParser
from app.domain.contracts import QueueJob
from app.models.llm import LLMClient
from app.services.feishu import FeishuService
from app.services.message_application import MessageApplicationService
from app.services.task_queue import PersistentTaskQueue, TaskWorker
from app.services.welcome import WelcomeService
from app.skills.registry import SkillRegistry
from config.settings import settings


class ApplicationRuntime:
    """Composition root for shared adapters, queue, and worker lifecycle."""

    def __init__(self, queue_path: str | Path | None = None) -> None:
        self.queue = PersistentTaskQueue(
            queue_path or settings.database_url,
            max_attempts=settings.task_queue_max_attempts,
        )
        self.llm = LLMClient()
        self.feishu = FeishuService()
        registry = SkillRegistry.default()
        self.message_service = MessageApplicationService(
            TaskParser(self.llm, skill_catalog=registry.catalog()),
            Agent(
                llm=self.llm,
                executor=Executor(registry),
            ),
            self.feishu,
        )
        self.welcome_service = WelcomeService(self.feishu)
        self.worker = TaskWorker(
            queue=self.queue,
            handlers={
                "message": self._handle_message,
                "welcome": self._handle_welcome,
            },
            concurrency=settings.task_worker_concurrency,
            poll_seconds=settings.task_queue_poll_seconds,
            dead_letter_handler=self._handle_dead_letter,
        )

    async def start(self) -> None:
        await self.worker.start()

    async def stop(self) -> None:
        await self.worker.stop()
        await self.feishu.aclose()
        await self.queue.close()

    async def enqueue_message(self, payload: dict[str, Any]) -> tuple[str, bool]:
        job_id = f"message:{self._event_identity(payload, 'message')}"
        accepted = await self.queue.enqueue(job_id, "message", payload)
        return job_id, accepted

    async def enqueue_welcome(
        self,
        payload: dict[str, Any],
        chat_id: str,
        users: list[dict[str, str]],
    ) -> tuple[str, bool]:
        job_id = f"welcome:{self._event_identity(payload, 'welcome')}"
        accepted = await self.queue.enqueue(
            job_id,
            "welcome",
            {"source": payload, "chat_id": chat_id, "users": users},
        )
        return job_id, accepted

    async def _handle_message(self, job: QueueJob) -> dict[str, object]:
        result = await self.message_service.process(
            job.payload,
            acknowledge=job.attempts == 1,
            job_id=job.job_id,
        )
        return result.model_dump(mode="json")

    async def _handle_welcome(self, job: QueueJob) -> dict[str, object]:
        chat_id = str(job.payload.get("chat_id") or "")
        raw_users = job.payload.get("users")
        users = [dict(item) for item in raw_users if isinstance(item, dict)] if isinstance(raw_users, list) else []
        return await self.welcome_service.send(chat_id, users)

    async def _handle_dead_letter(self, job: QueueJob, error: Exception) -> None:
        if job.kind == "message":
            await self.message_service.notify_failure(job.payload)

    @staticmethod
    def _event_identity(payload: dict[str, Any], fallback_prefix: str) -> str:
        event = payload.get("event")
        header = payload.get("header")
        if isinstance(event, dict):
            message = event.get("message")
            if isinstance(message, dict) and message.get("message_id"):
                return str(message["message_id"])
        if isinstance(header, dict) and header.get("event_id"):
            return str(header["event_id"])
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return f"{fallback_prefix}-{hashlib.sha256(serialized).hexdigest()[:24]}"
