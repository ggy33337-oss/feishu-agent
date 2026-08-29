from fastapi import APIRouter, HTTPException

from app.core.orchestrator.agent import Agent
from app.core.parser.task_parser import TaskParser
from app.services.feishu import FeishuService

router = APIRouter(prefix="/feishu", tags=["feishu"])


@router.post("/webhook")
async def receive_message(payload: dict) -> dict:
    """Receive a Feishu event callback and dispatch it to the agent."""
    if "challenge" in payload:
        return {"challenge": payload["challenge"]}

    header = payload.get("header", {})
    if header and header.get("event_type") != "im.message.receive_v1":
        return {"ok": True, "ignored": header.get("event_type")}

    try:
        parser = TaskParser()
        agent = Agent()
        feishu = FeishuService()

        task = await parser.parse(payload)
        result = await agent.run(task)

        if task.message_id:
            await feishu.reply(task.message_id, result.message)

        return {"ok": True, "task_id": task.task_id, "result": result.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
