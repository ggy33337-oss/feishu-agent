import asyncio
import json
import logging
from typing import Any

import lark_oapi as lark

from app.core.orchestrator.agent import Agent
from app.core.parser.task_parser import TaskParser
from app.services.feishu import FeishuService
from config.settings import settings

logger = logging.getLogger(__name__)


class FeishuWsBot:
    """Long-connection Feishu bot client."""

    def __init__(self) -> None:
        self.event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message)
            .build()
        )

    def start(self) -> None:
        client = lark.ws.Client(
            settings.feishu_app_id,
            settings.feishu_app_secret,
            event_handler=self.event_handler,
            log_level=lark.LogLevel.DEBUG,
        )
        client.start()

    def _on_message(self, data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        try:
            payload = json.loads(lark.JSON.marshal(data))
            logger.info("Received Feishu message event payload: %s", json.dumps(payload, ensure_ascii=False))
            logger.info("Received Feishu message raw: %s", data)
            asyncio.create_task(self._handle_message(payload))
        except Exception:
            logger.exception("Failed to handle Feishu message event.")

    async def _handle_message(self, payload: dict[str, Any]) -> None:
        try:
            parser = TaskParser()
            agent = Agent()
            feishu = FeishuService()

            task = await parser.parse(payload)
            logger.info("Structured task: %s", task.model_dump_json())
            result = await agent.run(task)
            logger.info("Skill result: %s", result.model_dump_json())

            if not task.message_id:
                raise ValueError("No message_id found in Feishu message event.")
            await feishu.reply(task.message_id, result.message)
            logger.info("Replied to Feishu message: %s", task.message_id)
        except Exception:
            logger.exception("Failed to process Feishu message event.")
            raise
