import json

import httpx

from config.settings import settings


class FeishuService:
    """Feishu reply service."""

    base_url = "https://open.feishu.cn/open-apis"

    async def get_tenant_access_token(self) -> str:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{self.base_url}/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": settings.feishu_app_id,
                    "app_secret": settings.feishu_app_secret,
                },
            )
        data = response.json()
        if response.status_code != 200 or data.get("code") != 0:
            raise RuntimeError(f"Failed to get Feishu tenant token: {data}")
        return data["tenant_access_token"]

    async def send_text(self, receive_id: str, receive_id_type: str, text: str) -> dict:
        token = await self.get_tenant_access_token()
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{self.base_url}/im/v1/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={"receive_id_type": receive_id_type},
                json={
                    "receive_id": receive_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": text}),
                },
            )
        data = response.json()
        if response.status_code != 200 or data.get("code") != 0:
            raise RuntimeError(f"Failed to send Feishu message: {data}")
        return data

    async def reply(self, message_id: str, text: str) -> dict:
        token = await self.get_tenant_access_token()
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{self.base_url}/im/v1/messages/{message_id}/reply",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "msg_type": "text",
                    "content": json.dumps({"text": text}),
                },
            )
        data = response.json()
        if response.status_code != 200 or data.get("code") != 0:
            raise RuntimeError(f"Failed to reply Feishu message: {data}")
        return data
