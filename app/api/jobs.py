# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import require_admin

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id:path}")
async def get_job(
    job_id: str,
    request: Request,
    actor: str = Depends(require_admin),
) -> dict:
    job = await request.app.state.runtime.queue.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在。")
    return job.model_dump(mode="json")
