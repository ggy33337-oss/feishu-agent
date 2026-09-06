# -*- coding: utf-8 -*-
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.api.feishu_webhook import router as feishu_router
from app.api.jobs import router as jobs_router
from app.api.welcome_admin import router as welcome_admin_router
from app.services.runtime import ApplicationRuntime
from app.services.database import close_database
from app.services.logging_setup import configure_process_logging


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    configure_process_logging("api")
    runtime = ApplicationRuntime()
    app.state.runtime = runtime
    await runtime.start()
    try:
        yield
    finally:
        await runtime.stop()
        await close_database()


app = FastAPI(title="Feishu AI Agent", lifespan=lifespan)
app.include_router(feishu_router)
app.include_router(jobs_router)
app.include_router(welcome_admin_router)


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/welcome-admin")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
