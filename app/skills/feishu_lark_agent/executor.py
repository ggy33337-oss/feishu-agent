from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from config.settings import settings


class FeishuLarkAgentExecutor:
    def __init__(self, script_path: str | Path | None = None) -> None:
        self.script_path = Path(script_path) if script_path else Path(__file__).with_name("feishu.py")

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute_sync, inputs)

    def _execute_sync(self, inputs: dict[str, Any]) -> dict[str, Any]:
        category, action, flags = self._resolve_command(inputs)
        cmd = [sys.executable, str(self.script_path), category, action]
        for key, value in flags.items():
            if value is None or value is False:
                continue
            flag = f"--{key.replace('_', '-')}"
            if value is True:
                cmd.append(flag)
            else:
                cmd.extend([flag, self._stringify(value)])

        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=self._build_env(),
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "Feishu CLI failed.")

        output = completed.stdout.strip()
        if not output:
            return {"ok": True, "output": ""}
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {"ok": True, "output": output}

    def _resolve_command(self, inputs: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        params = inputs.get("parameters") if isinstance(inputs.get("parameters"), dict) else inputs
        if "command" in params and isinstance(params["command"], str):
            parts = params["command"].split()
            if len(parts) != 2:
                raise ValueError("command must be in '<category> <action>' format")
            category, action = parts
            flags = params.get("flags") if isinstance(params.get("flags"), dict) else {}
            return category, action, flags

        category = params.get("category")
        action = params.get("action")
        flags = params.get("flags") if isinstance(params.get("flags"), dict) else {}
        if not category or not action:
            raise ValueError("Feishu Lark command needs category/action or command.")
        return str(category), str(action), flags

    def _stringify(self, value: Any) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if settings.feishu_app_id:
            env["FEISHU_APP_ID"] = settings.feishu_app_id
        if settings.feishu_app_secret:
            env["FEISHU_APP_SECRET"] = settings.feishu_app_secret
        if settings.feishu_owner_open_id:
            env["FEISHU_OWNER_OPEN_ID"] = settings.feishu_owner_open_id
        return env
