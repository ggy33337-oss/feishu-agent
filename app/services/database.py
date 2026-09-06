# -*- coding: utf-8 -*-
"""Shared asynchronous SQLAlchemy database configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from config.settings import settings


def sqlite_url(path: Path) -> str:
    """Build a test-only async SQLite URL from a filesystem path."""
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def create_engine(database_url: str) -> AsyncEngine:
    options: dict[str, Any] = {
        "echo": settings.database_echo,
        "pool_pre_ping": True,
        "pool_recycle": settings.database_pool_recycle,
    }
    if not database_url.startswith("sqlite+"):
        options.update(
            {
                "pool_size": settings.database_pool_size,
                "max_overflow": settings.database_max_overflow,
            }
        )
    return create_async_engine(database_url, **options)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


# FastAPI dependencies can reuse one process-level pool instead of opening a
# new engine for every request.
async_engine = create_engine(settings.database_url)
AsyncSessionLocal = create_session_factory(async_engine)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency for request-scoped asynchronous database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def close_database() -> None:
    await async_engine.dispose()
