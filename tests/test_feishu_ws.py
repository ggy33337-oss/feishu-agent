# -*- coding: utf-8 -*-
from app.services.feishu_ws import FeishuWsBot


def test_feishu_message_claim_deduplicates_retries(tmp_path) -> None:
    bot = FeishuWsBot()
    bot.claim_store_path = tmp_path / "claims.sqlite3"

    assert bot._claim_message("om_retry") is True
    assert bot._claim_message("om_retry") is False
    assert bot._claim_message("om_other") is True


def test_feishu_message_claim_is_shared_between_bot_instances(tmp_path) -> None:
    claim_store = tmp_path / "claims.sqlite3"
    first_bot = FeishuWsBot()
    second_bot = FeishuWsBot()
    first_bot.claim_store_path = claim_store
    second_bot.claim_store_path = claim_store

    assert first_bot._claim_message("om_shared") is True
    assert second_bot._claim_message("om_shared") is False


def test_member_added_users_extracts_unique_open_ids() -> None:
    bot = FeishuWsBot()
    payload = {
        "event": {
            "users": [
                {"name": "张三", "user_id": {"open_id": "ou_1"}},
                {"name": "张三", "user_id": {"open_id": "ou_1"}},
                {"name": "李四", "user_id": {"open_id": "ou_2"}},
            ]
        }
    }

    assert bot._member_added_users(payload) == [
        {"open_id": "ou_1", "name": "张三"},
        {"open_id": "ou_2", "name": "李四"},
    ]


def test_member_added_chat_id_extracts_source_group() -> None:
    bot = FeishuWsBot()

    assert bot._member_added_chat_id({"event": {"chat_id": "oc_group"}}) == "oc_group"
    assert bot._member_added_chat_id({"event": {}}) is None
