# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from typing import Any

from app.core.orchestrator.agent import Agent
from app.core.parser.task_parser import TaskParser
from app.domain.contracts import SkillResult
from app.services.feishu import FeishuService
from app.services.timing import timed_stage

import logging


logger = logging.getLogger(__name__)


class MessageApplicationService:
    """Transport-neutral use case for processing one inbound Feishu message."""

    def __init__(self, parser: TaskParser, agent: Agent, feishu: FeishuService) -> None:
        self.parser = parser
        self.agent = agent
        self.feishu = feishu

    async def process(
        self,
        payload: dict[str, Any],
        acknowledge: bool = True,
        job_id: str | None = None,
    ) -> SkillResult:
        message_id = self.message_id(payload)
        trace_id = job_id or message_id
        acknowledge_task: asyncio.Task[None] | None = None
        if message_id and acknowledge:
            acknowledge_task = asyncio.create_task(
                self._send_ack(message_id, trace_id),
                name=f"feishu-ack-{message_id}",
            )
        try:
            async with timed_stage(logger, "task.parse", job_id=trace_id):
                task = await self.parser.parse(payload, job_id=trace_id)
            if task.message_id and task.attachments:
                async with timed_stage(
                    logger,
                    "attachments.materialize",
                    job_id=trace_id,
                    fields={"task_id": task.task_id, "count": len(task.attachments)},
                ):
                    task.attachments = await self.feishu.materialize_attachments(
                        task.message_id,
                        task.task_id,
                        task.attachments,
                    )
            async with timed_stage(
                logger,
                "agent.run",
                job_id=trace_id,
                fields={"task_id": task.task_id},
            ):
                result = await self.agent.run(task, job_id=trace_id)
            if not task.message_id:
                raise ValueError("No message_id found in Feishu message event.")
            async with timed_stage(
                logger,
                "feishu.reply.final",
                job_id=trace_id,
                fields={"task_id": task.task_id, "artifacts": len(result.artifacts)},
            ):
                await self.feishu.reply(task.message_id, result.message)
                await self.feishu.reply_artifacts(task.message_id, result.artifacts)
            return result
        finally:
            if acknowledge_task is not None:
                await acknowledge_task

    async def _send_ack(self, message_id: str, trace_id: str | None) -> None:
        try:
            async with timed_stage(logger, "feishu.reply.ack", job_id=trace_id):
                await self.feishu.reply(message_id, "已收到，正在处理你的请求……")
        except Exception:
            # Acknowledgement is best effort; it must not delay or retry the
            # actual task when Feishu is temporarily unavailable.
            logger.exception("Feishu acknowledgement failed for %s", message_id)

    async def notify_failure(self, payload: dict[str, Any]) -> None:
        message_id = self.message_id(payload)
        if message_id:
            await self.feishu.reply(message_id, "处理失败，请稍后重试。系统已记录本次异常。")

    @staticmethod
    def message_id(payload: dict[str, Any]) -> str | None:
        event = payload.get("event")
        message = event.get("message") if isinstance(event, dict) else None
        value = message.get("message_id") if isinstance(message, dict) else None
        return str(value) if value else None
