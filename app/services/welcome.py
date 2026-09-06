# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any

import yaml

from app.services.feishu import FeishuService

logger = logging.getLogger(__name__)


class WelcomeService:
    """Mention new members in their group and direct them to the pinned notice."""

    project_root = Path(__file__).resolve().parents[2]
    config_path = project_root / "config" / "welcome.yaml"
    default_message = "欢迎加入本群，请查看置顶群公告获取相关资料。"

    def __init__(self, feishu: FeishuService | None = None) -> None:
        self.feishu = feishu or FeishuService()

    async def send(self, chat_id: str, users: list[dict[str, str]]) -> dict[str, int | bool]:
        config = self.load_config()
        if not config.get("enabled", True):
            return {"enabled": False, "users": 0, "messages": 0}

        group_id = str(chat_id or "").strip()
        if not group_id:
            raise ValueError("A chat_id is required for the group welcome message.")

        recipients = self._recipients(users)
        if not recipients:
            return {"enabled": True, "users": 0, "messages": 0}

        message = str(config.get("message") or self.default_message).strip()
        mentions = " ".join(
            f'<at user_id="{html.escape(recipient["open_id"], quote=True)}">'
            f'{html.escape(recipient["name"] or "新成员")}</at>'
            for recipient in recipients
        )
        text = f"{mentions} {message}".strip()
        await self.feishu.send_text(group_id, "chat_id", text)
        return {"enabled": True, "users": len(recipients), "messages": 1}

    def load_config(self) -> dict[str, Any]:
        if not self.config_path.is_file():
            logger.warning("Welcome config not found: %s", self.config_path)
            return {"enabled": False}
        with open(self.config_path, encoding="utf-8") as file_handle:
            loaded = yaml.safe_load(file_handle) or {}
        if not isinstance(loaded, dict):
            raise ValueError("config/welcome.yaml must contain a YAML object.")
        return loaded

    def save_config(self, config: dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(".yaml.tmp")
        with open(temporary, "w", encoding="utf-8", newline="\n") as file_handle:
            yaml.safe_dump(config, file_handle, allow_unicode=True, sort_keys=False)
        temporary.replace(self.config_path)

    @staticmethod
    def _recipients(users: list[dict[str, str]]) -> list[dict[str, str]]:
        recipients: list[dict[str, str]] = []
        seen: set[str] = set()
        for user in users:
            open_id = str(user.get("open_id") or "").strip()
            if not open_id or open_id in seen:
                continue
            seen.add(open_id)
            recipients.append({"open_id": open_id, "name": str(user.get("name") or "").strip()})
        return recipients
