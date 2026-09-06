# -*- coding: utf-8 -*-
from fastapi.testclient import TestClient

from app.api import welcome_admin
from app.main import app
from config.settings import settings


def test_welcome_admin_page_manages_group_message_only() -> None:
    client = TestClient(app)

    response = client.get("/welcome-admin")

    assert response.status_code == 200
    assert '<meta charset="UTF-8">' in response.text
    assert "群内提示文案" in response.text
    assert "@新成员" in response.text
    assert "添加文件" not in response.text
    assert 'type="file"' not in response.text


def test_welcome_settings_update_removes_legacy_file_configuration(tmp_path, monkeypatch) -> None:
    config = tmp_path / "welcome.yaml"
    config.write_text(
        "enabled: true\n"
        "message: 旧文案\n"
        "files:\n"
        "  - path: 旧资料.pdf\n"
        "    enabled: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(welcome_admin.service, "config_path", config)
    client = TestClient(app)

    response = client.put(
        "/api/welcome",
        json={"enabled": True, "message": "欢迎加入，请查看置顶群公告。"},
    )

    assert response.status_code == 200
    assert client.get("/api/welcome").json() == {
        "enabled": True,
        "message": "欢迎加入，请查看置顶群公告。",
    }
    saved = welcome_admin.service.load_config()
    assert saved == {"enabled": True, "message": "欢迎加入，请查看置顶群公告。"}


def test_welcome_api_requires_configured_admin_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_key", "secret")
    client = TestClient(app)

    assert client.get("/api/welcome").status_code == 401
    assert client.get("/api/welcome", headers={"X-Admin-Key": "secret"}).status_code == 200
