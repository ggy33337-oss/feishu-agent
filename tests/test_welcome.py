# -*- coding: utf-8 -*-
import asyncio

from app.services.welcome import WelcomeService


class FakeFeishu:
    def __init__(self) -> None:
        self.texts: list[tuple[str, str, str]] = []

    async def send_text(self, receive_id: str, receive_id_type: str, text: str) -> dict:
        self.texts.append((receive_id, receive_id_type, text))
        return {"code": 0}


def test_welcome_service_mentions_new_members_in_group(tmp_path) -> None:
    config = tmp_path / "welcome.yaml"
    config.write_text(
        "enabled: true\n"
        "message: 欢迎加入本群，请查看置顶群公告获取相关资料。\n",
        encoding="utf-8",
    )
    fake = FakeFeishu()
    service = WelcomeService(fake)  # type: ignore[arg-type]
    service.config_path = config

    result = asyncio.run(
        service.send(
            "oc_group",
            [
                {"open_id": "ou_1", "name": "张三"},
                {"open_id": "ou_2", "name": "李四"},
            ],
        )
    )

    assert result == {"enabled": True, "users": 2, "messages": 1}
    assert fake.texts == [
        (
            "oc_group",
            "chat_id",
            '<at user_id="ou_1">张三</at> <at user_id="ou_2">李四</at> '
            "欢迎加入本群，请查看置顶群公告获取相关资料。",
        )
    ]


def test_welcome_service_escapes_member_display_name(tmp_path) -> None:
    config = tmp_path / "welcome.yaml"
    config.write_text("enabled: true\nmessage: 查看群公告。\n", encoding="utf-8")
    fake = FakeFeishu()
    service = WelcomeService(fake)  # type: ignore[arg-type]
    service.config_path = config

    asyncio.run(service.send("oc_group", [{"open_id": "ou_1", "name": "<新人>"}]))

    assert fake.texts[0][2] == '<at user_id="ou_1">&lt;新人&gt;</at> 查看群公告。'
