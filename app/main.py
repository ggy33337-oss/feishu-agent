from fastapi import FastAPI

from app.api.feishu_webhook import router as feishu_router

app = FastAPI(title="Feishu AI Agent")
app.include_router(feishu_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

