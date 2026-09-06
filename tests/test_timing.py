# -*- coding: utf-8 -*-
import asyncio
import json
import logging

from app.services.timing import timed_stage


def test_timed_stage_writes_structured_utf8_event(caplog) -> None:
    async def scenario() -> None:
        logger = logging.getLogger("timing-test")
        async with timed_stage(
            logger,
            "search.translate",
            job_id="message:test",
            fields={"count": 5},
        ):
            await asyncio.sleep(0)

    with caplog.at_level(logging.INFO, logger="timing-test"):
        asyncio.run(scenario())

    record = next(item for item in caplog.records if item.name == "timing-test")
    payload = json.loads(record.getMessage().split("stage_timing ", 1)[1])
    assert payload["event"] == "stage_timing"
    assert payload["stage"] == "search.translate"
    assert payload["job_id"] == "message:test"
    assert payload["status"] == "ok"
    assert payload["count"] == 5
    assert payload["elapsed_ms"] >= 0


def test_timed_stage_writes_exception_details(caplog) -> None:
    async def scenario() -> None:
        logger = logging.getLogger("timing-error-test")
        try:
            async with timed_stage(logger, "tool.execute.search", job_id="message:error"):
                raise ValueError("invalid search arguments")
        except ValueError:
            pass

    with caplog.at_level(logging.INFO, logger="timing-error-test"):
        asyncio.run(scenario())

    record = next(item for item in caplog.records if item.name == "timing-error-test")
    payload = json.loads(record.getMessage().split("stage_timing ", 1)[1])
    assert payload["status"] == "error"
    assert payload["error_type"] == "ValueError"
    assert payload["error_message"] == "invalid search arguments"
    assert "ValueError: invalid search arguments" in payload["error_traceback"]
