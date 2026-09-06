# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.ports.storage import ArtifactStore
from app.services.storage import LocalArtifactStore
from config.settings import settings

logger = logging.getLogger(__name__)


class FeishuService:
    """Feishu reply service."""

    base_url = "https://open.feishu.cn/open-apis"
    max_request_attempts = 3
    retry_backoff_seconds = 0.5
    retryable_status_codes = frozenset({408, 425, 429, 500, 502, 503, 504})

    def __init__(self, artifact_store: ArtifactStore | None = None) -> None:
        self.artifact_store = artifact_store or LocalArtifactStore()
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def _request(self, method: str, url: str, *, timeout: float, **kwargs: Any) -> httpx.Response:
        retryable_exceptions = (
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
            httpx.RemoteProtocolError,
        )
        for attempt in range(1, self.max_request_attempts + 1):
            try:
                if self._client is None:
                    async with self._client_lock:
                        if self._client is None:
                            self._client = httpx.AsyncClient()
                response = await getattr(self._client, method)(url, timeout=timeout, **kwargs)
            except retryable_exceptions as exc:
                if attempt >= self.max_request_attempts:
                    raise
                logger.warning(
                    "Feishu %s request failed (attempt %s/%s): %s",
                    method.upper(),
                    attempt,
                    self.max_request_attempts,
                    exc,
                )
                await asyncio.sleep(self.retry_backoff_seconds * attempt)
                continue

            if response.status_code in self.retryable_status_codes and attempt < self.max_request_attempts:
                logger.warning(
                    "Feishu %s request returned HTTP %s (attempt %s/%s)",
                    method.upper(),
                    response.status_code,
                    attempt,
                    self.max_request_attempts,
                )
                await asyncio.sleep(self.retry_backoff_seconds * attempt)
                continue
            return response

        raise RuntimeError("Feishu request failed after retries.")

    async def get_tenant_access_token(self) -> str:
        if self._token and self._token_expires_at > time.monotonic() + 120:
            return self._token
        async with self._token_lock:
            if self._token and self._token_expires_at > time.monotonic() + 120:
                return self._token
            response = await self._request(
                "post",
                f"{self.base_url}/auth/v3/tenant_access_token/internal",
                timeout=20,
                json={
                    "app_id": settings.feishu_app_id,
                    "app_secret": settings.feishu_app_secret,
                },
            )
            data = response.json()
            if response.status_code != 200 or data.get("code") != 0:
                raise RuntimeError(f"Failed to get Feishu tenant token: {data}")
            self._token = str(data["tenant_access_token"])
            self._token_expires_at = time.monotonic() + int(data.get("expire") or 7200)
            return self._token

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def send_text(self, receive_id: str, receive_id_type: str, text: str) -> dict:
        token = await self.get_tenant_access_token()
        response = await self._request(
            "post",
            f"{self.base_url}/im/v1/messages",
            timeout=20,
            headers={"Authorization": f"Bearer {token}"},
            params={"receive_id_type": receive_id_type},
            json={
                "receive_id": receive_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )
        data = response.json()
        if response.status_code != 200 or data.get("code") != 0:
            raise RuntimeError(f"Failed to send Feishu message: {data}")
        return data

    async def reply(self, message_id: str, text: str) -> dict:
        token = await self.get_tenant_access_token()
        response = await self._request(
            "post",
            f"{self.base_url}/im/v1/messages/{message_id}/reply",
            timeout=20,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )
        data = response.json()
        if response.status_code != 200 or data.get("code") != 0:
            raise RuntimeError(f"Failed to reply Feishu message: {data}")
        return data

    async def materialize_attachments(
        self,
        message_id: str,
        task_id: str,
        attachments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        materialized: list[dict[str, Any]] = []
        input_dir = self.artifact_store.input_dir(task_id)
        for index, attachment in enumerate(attachments, start=1):
            item = dict(attachment)
            file_key = str(item.get("file_key") or "").strip()
            if not file_key or item.get("local_path"):
                materialized.append(item)
                continue
            file_name = self._safe_file_name(str(item.get("name") or f"attachment-{index}.xlsx"))
            local_path = input_dir / file_name
            await self.download_message_resource(message_id, file_key, local_path)
            item["local_path"] = str(local_path)
            materialized.append(item)
        return materialized

    async def download_message_resource(self, message_id: str, file_key: str, output_path: Path) -> None:
        token = await self.get_tenant_access_token()
        response = await self._request(
            "get",
            f"{self.base_url}/im/v1/messages/{message_id}/resources/{file_key}",
            timeout=60,
            headers={"Authorization": f"Bearer {token}"},
            params={"type": "file"},
        )
        if response.status_code != 200:
            raise RuntimeError(f"Failed to download Feishu attachment ({response.status_code}).")
        output_path.write_bytes(response.content)

    async def reply_artifacts(self, message_id: str, artifacts: list[dict[str, Any]]) -> None:
        for artifact in artifacts:
            if artifact.get("type") != "file" or not artifact.get("path"):
                continue
            path = Path(str(artifact["path"]))
            if not path.is_file():
                raise ValueError(f"Artifact file not found: {path}")
            file_key = await self.upload_file(path, str(artifact.get("name") or path.name))
            await self.reply_file(message_id, file_key)

    async def upload_file(self, path: Path, file_name: str) -> str:
        token = await self.get_tenant_access_token()
        file_type = {
            ".pdf": "pdf",
            ".doc": "doc",
            ".docx": "doc",
            ".xls": "xls",
            ".xlsx": "xls",
            ".ppt": "ppt",
            ".pptx": "ppt",
        }.get(path.suffix.lower(), "stream")
        response = await self._request(
            "post",
            f"{self.base_url}/im/v1/files",
            timeout=60,
            headers={"Authorization": f"Bearer {token}"},
            data={"file_type": file_type, "file_name": file_name},
            files={"file": (file_name, path.read_bytes(), "application/octet-stream")},
        )
        data = response.json()
        if response.status_code != 200 or data.get("code") != 0:
            raise RuntimeError(f"Failed to upload Feishu file: {data}")
        return str(data["data"]["file_key"])

    async def reply_file(self, message_id: str, file_key: str) -> dict[str, Any]:
        token = await self.get_tenant_access_token()
        response = await self._request(
            "post",
            f"{self.base_url}/im/v1/messages/{message_id}/reply",
            timeout=20,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "msg_type": "file",
                "content": json.dumps({"file_key": file_key}, ensure_ascii=False),
            },
        )
        data = response.json()
        if response.status_code != 200 or data.get("code") != 0:
            raise RuntimeError(f"Failed to reply Feishu file: {data}")
        return data

    def _safe_file_name(self, value: str) -> str:
        cleaned = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", value).strip("._")
        return cleaned[:100] or "attachment.xlsx"
