# -*- coding: utf-8 -*-
import secrets

from fastapi import HTTPException, Request, status

from config.settings import settings


async def require_admin(request: Request) -> str:
    configured = settings.admin_api_key.strip()
    if not configured:
        if settings.app_env.lower() in {"dev", "test"}:
            return "development"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_API_KEY 未配置。",
        )
    authorization = request.headers.get("Authorization", "")
    bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    provided = request.headers.get("X-Admin-Key", "").strip() or bearer
    if not provided or not secrets.compare_digest(provided, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="管理凭证无效。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return "api-key"

