# -*- coding: utf-8 -*-
"""Structured timing events for queue jobs and external calls."""

from __future__ import annotations

import json
import logging
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator
from zoneinfo import ZoneInfo


def _now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def _write_event(
    logger: logging.Logger,
    *,
    stage: str,
    job_id: str | None,
    status: str,
    started_at: datetime,
    finished_at: datetime,
    elapsed_ms: float,
    fields: dict[str, Any] | None = None,
    error: BaseException | None = None,
) -> None:
    event: dict[str, Any] = {
        "event": "stage_timing",
        "stage": stage,
        "job_id": job_id,
        "status": status,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "elapsed_ms": round(elapsed_ms, 3),
    }
    if fields:
        event.update(fields)
    if error is not None:
        # Keep the exception details in the same event as the duration.  This
        # makes a failed stage diagnosable from one JSON line and preserves the
        # original exception for the caller to handle/retry.
        event.update(
            {
                "error_type": type(error).__name__,
                "error_message": str(error)[:2000],
                "error_traceback": "".join(traceback.format_exception(error))[-8000:],
            }
        )
    logger.info(
        "stage_timing %s",
        json.dumps(event, ensure_ascii=False, sort_keys=True, default=str),
    )


@asynccontextmanager
async def timed_stage(
    logger: logging.Logger,
    stage: str,
    *,
    job_id: str | None = None,
    fields: dict[str, Any] | None = None,
) -> AsyncIterator[None]:
    started_at = _now()
    started = time.perf_counter()
    try:
        yield
    except BaseException as error:
        _write_event(
            logger,
            stage=stage,
            job_id=job_id,
            status="error",
            started_at=started_at,
            finished_at=_now(),
            elapsed_ms=(time.perf_counter() - started) * 1000,
            fields=fields,
            error=error,
        )
        raise
    else:
        _write_event(
            logger,
            stage=stage,
            job_id=job_id,
            status="ok",
            started_at=started_at,
            finished_at=_now(),
            elapsed_ms=(time.perf_counter() - started) * 1000,
            fields=fields,
        )
