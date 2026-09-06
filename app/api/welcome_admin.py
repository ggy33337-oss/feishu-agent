# -*- coding: utf-8 -*-
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator

from app.services.welcome import WelcomeService
from app.api.dependencies import require_admin
from app.services.audit import AuditService

router = APIRouter(tags=["welcome-admin"])
service = WelcomeService()
audit = AuditService()
project_root = Path(__file__).resolve().parents[2]
admin_page_path = project_root / "app" / "static" / "welcome_admin.html"


class WelcomeSettingsUpdate(BaseModel):
    enabled: bool
    message: str = Field(min_length=1, max_length=1000)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("提示文案不能为空。")
        return normalized


@router.get("/welcome-admin", response_class=HTMLResponse)
async def welcome_admin_page() -> HTMLResponse:
    return HTMLResponse(admin_page_path.read_text(encoding="utf-8"))


@router.get("/api/welcome")
async def get_welcome_settings(actor: str = Depends(require_admin)) -> dict:
    config = service.load_config()
    return {
        "enabled": bool(config.get("enabled", True)),
        "message": str(config.get("message") or service.default_message),
    }


@router.put("/api/welcome")
async def update_welcome_settings(
    payload: WelcomeSettingsUpdate,
    request: Request,
    actor: str = Depends(require_admin),
) -> dict:
    before = service.load_config()
    after = {"enabled": payload.enabled, "message": payload.message}
    service.save_config(after)
    await audit.record(
        action="welcome.settings.update",
        actor=actor,
        source=request.client.host if request.client else "unknown",
        before=before,
        after=after,
    )
    return {"ok": True}
