# -*- coding: utf-8 -*-
from fastapi import APIRouter, Request, Response, status

router = APIRouter(prefix="/feishu", tags=["feishu"])


@router.post("/webhook")
async def receive_message(payload: dict, request: Request, response: Response) -> dict:
    """Persist an event and acknowledge it before slow AI work begins."""
    if "challenge" in payload:
        return {"challenge": payload["challenge"]}

    header = payload.get("header", {})
    if header and header.get("event_type") != "im.message.receive_v1":
        return {"ok": True, "ignored": header.get("event_type")}

    job_id, accepted = await request.app.state.runtime.enqueue_message(payload)
    response.status_code = status.HTTP_202_ACCEPTED
    return {
        "ok": True,
        "accepted": accepted,
        "duplicate": not accepted,
        "job_id": job_id,
        "status": "pending" if accepted else "already_queued",
    }
