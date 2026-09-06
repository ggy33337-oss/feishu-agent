# -*- coding: utf-8 -*-
import asyncio

import httpx

from app.services.feishu import FeishuService


class FakeResponse:
    status_code = 200

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def json(self) -> dict:
        return self.payload


def test_feishu_reply_retries_transient_network_failure(monkeypatch) -> None:
    service = FeishuService()
    service.retry_backoff_seconds = 0
    reply_attempts = 0

    async def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal reply_attempts
        if "/auth/" in url:
            return FakeResponse({"code": 0, "tenant_access_token": "token"})
        reply_attempts += 1
        if reply_attempts == 1:
            raise httpx.ReadTimeout("temporary timeout")
        return FakeResponse({"code": 0})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = asyncio.run(service.reply("om_test", "完成"))

    assert result == {"code": 0}
    assert reply_attempts == 2
