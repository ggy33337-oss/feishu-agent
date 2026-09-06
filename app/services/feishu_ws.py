# -*- coding: utf-8 -*-
import asyncio
import json
import logging
from collections import deque
from typing import Any

import lark_oapi as lark

from app.services.runtime import ApplicationRuntime
from config.settings import settings

logger = logging.getLogger(__name__)


class FeishuWsBot:
    """Long-connection Feishu bot client."""

    _process_claims: set[str] = set()
    def __init__(self, runtime: ApplicationRuntime | None = None) -> None:
        self.runtime = runtime or ApplicationRuntime()
        self._handled_message_ids: set[str] = set()
        self._handled_message_order: deque[str] = deque(maxlen=2048)
        self.event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message)
            .register_p2_im_chat_member_user_added_v1(self._on_members_added)
            .build()
        )

    def start(self) -> None:
        client = lark.ws.Client(
            settings.feishu_app_id,
            settings.feishu_app_secret,
            event_handler=self.event_handler,
            log_level=lark.LogLevel.WARNING,
        )
        client.start()

    def _on_message(self, data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        try:
            payload = json.loads(lark.JSON.marshal(data))
            message_id = self._message_id(payload)
            logger.info("Received Feishu message: %s", message_id or "unknown")
            asyncio.create_task(self._enqueue_message(payload))
        except Exception:
            logger.exception("Failed to handle Feishu message event.")

    def _on_members_added(self, data: lark.im.v1.P2ImChatMemberUserAddedV1) -> None:
        try:
            payload = json.loads(lark.JSON.marshal(data))
            event_id = self._event_id(payload)
            users = self._member_added_users(payload)
            chat_id = self._member_added_chat_id(payload)
            if not users or not chat_id:
                logger.info(
                    "Ignoring member-added event without usable chat_id/open_id: %s",
                    event_id or "unknown",
                )
                return
            logger.info(
                "Received Feishu member-added event %s for %s user(s) in chat %s",
                event_id or "unknown",
                len(users),
                chat_id,
            )
            asyncio.create_task(self._enqueue_members_added(payload, chat_id, users))
        except Exception:
            logger.exception("Failed to handle Feishu member-added event.")

    async def _enqueue_members_added(
        self,
        payload: dict[str, Any],
        chat_id: str,
        users: list[dict[str, str]],
    ) -> None:
        await self.runtime.start()
        job_id, accepted = await self.runtime.enqueue_welcome(payload, chat_id, users)
        logger.info("Welcome job %s: %s", "queued" if accepted else "deduplicated", job_id)

    async def _enqueue_message(self, payload: dict[str, Any]) -> None:
        await self.runtime.start()
        job_id, accepted = await self.runtime.enqueue_message(payload)
        logger.info("Message job %s: %s", "queued" if accepted else "deduplicated", job_id)

    async def _handle_message(self, payload: dict[str, Any]) -> None:
        try:
            result = await self.runtime.message_service.process(payload)
            logger.info("Skill result: %s", result.model_dump_json())
        except Exception:
            logger.exception("Failed to process Feishu message event.")
            await self.runtime.message_service.notify_failure(payload)

    def _message_id(self, payload: dict[str, Any]) -> str | None:
        event = payload.get("event")
        if not isinstance(event, dict):
            return None
        message = event.get("message")
        if not isinstance(message, dict):
            return None
        value = message.get("message_id")
        return str(value) if value else None

    def _event_id(self, payload: dict[str, Any]) -> str | None:
        header = payload.get("header")
        if not isinstance(header, dict):
            return None
        value = header.get("event_id")
        return str(value) if value else None

    def _member_added_users(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        event = payload.get("event")
        if not isinstance(event, dict):
            return []
        users: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in event.get("users", []):
            if not isinstance(item, dict):
                continue
            user_id = item.get("user_id")
            if not isinstance(user_id, dict):
                continue
            open_id = str(user_id.get("open_id") or "").strip()
            if not open_id or open_id in seen:
                continue
            seen.add(open_id)
            users.append({"open_id": open_id, "name": str(item.get("name") or "").strip()})
        return users

    def _member_added_chat_id(self, payload: dict[str, Any]) -> str | None:
        event = payload.get("event")
        if not isinstance(event, dict):
            return None
        value = event.get("chat_id")
        return str(value).strip() if value else None

    def _claim_message(self, message_id: str) -> bool:
        """Keep a short in-process guard; the MySQL queue provides durable idempotency."""
        if message_id in self._handled_message_ids or message_id in self._process_claims:
            return False
        if len(self._handled_message_order) == self._handled_message_order.maxlen:
            expired = self._handled_message_order.popleft()
            self._handled_message_ids.discard(expired)
            self._process_claims.discard(expired)
        self._handled_message_ids.add(message_id)
        self._process_claims.add(message_id)
        self._handled_message_order.append(message_id)
        return True
