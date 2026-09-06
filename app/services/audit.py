# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


class AuditService:
    def __init__(self, path: Path | None = None) -> None:
        project_root = Path(__file__).resolve().parents[2]
        self.path = path or project_root / "outputs" / "admin_audit.jsonl"
        self._lock = asyncio.Lock()

    async def record(
        self,
        action: str,
        actor: str,
        source: str,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> None:
        event = {
            "timestamp": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "action": action,
            "actor": actor,
            "source": source,
            "before": before,
            "after": after,
        }
        async with self._lock:
            await asyncio.to_thread(self._append, event)

    def _append(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8", newline="\n") as file_handle:
            file_handle.write(json.dumps(event, ensure_ascii=False) + "\n")

